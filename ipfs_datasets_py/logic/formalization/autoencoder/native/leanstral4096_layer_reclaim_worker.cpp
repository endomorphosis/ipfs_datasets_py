// Source-only native feature extraction. This is not a semantic/proof verifier.
// The parent must authenticate this binary, native libraries and model contents,
// admit resources, keep the model FD open, and require a successful closing row.
#include "llama.h"
#include "readonly_model_reclaim.hpp"
#include "ggml-backend.h"
#include "ggml-cpu.h"
#include "ggml-alloc.h"
#include "json.hpp"
#include <openssl/sha.h>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstdint>
#include <fcntl.h>
#include <fstream>
#include <functional>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <memory>
#include <poll.h>
#include <cerrno>
#include <sys/syscall.h>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <unistd.h>
#include <vector>

#ifndef OWNER_SOURCE_SHA256
#define OWNER_SOURCE_SHA256 "unbound-build"
#endif

using json = nlohmann::json;
using Clock = std::chrono::steady_clock;
static constexpr int LIMIT = 512;
static constexpr int DIMENSION = 4096;
static constexpr std::size_t MAX_REQUEST_BYTES = 16 * 1024 * 1024;
static volatile std::sig_atomic_t interrupted = 0;

static void on_signal(int) { interrupted = 1; }
static void require(bool value, const char * message) {
    if (!value) throw std::runtime_error(message);
}
static std::string sha256(const std::string & value) {
    unsigned char out[SHA256_DIGEST_LENGTH];
    SHA256(reinterpret_cast<const unsigned char *>(value.data()), value.size(), out);
    std::ostringstream result;
    for (unsigned char byte : out) result << std::hex << std::setw(2) << std::setfill('0') << static_cast<int>(byte);
    return result.str();
}
static bool hex64(const std::string & value) {
    return value.size() == 64 && std::all_of(value.begin(), value.end(), [](char c) {
        return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f');
    });
}
static void keys(const json & value, const std::set<std::string> & expected) {
    require(value.is_object(), "closed object required");
    std::set<std::string> actual;
    for (auto it = value.begin(); it != value.end(); ++it) actual.insert(it.key());
    require(actual == expected, "unexpected request field");
}
static std::string bounded_read(std::istream & stream) {
    std::string result;
    char chunk[8192];
    while (stream.good()) {
        stream.read(chunk, sizeof(chunk));
        result.append(chunk, static_cast<std::size_t>(stream.gcount()));
        require(result.size() <= MAX_REQUEST_BYTES, "request exceeds byte limit");
    }
    require(!result.empty(), "empty request");
    return result;
}
static json parse_request(const std::string & raw, const std::string & nonce) {
    // nlohmann otherwise silently keeps the last duplicate object key.
    std::vector<std::set<std::string>> seen;
    auto callback = [&seen](int, json::parse_event_t event, json & value) {
        if (event == json::parse_event_t::object_start) seen.emplace_back();
        if (event == json::parse_event_t::key) {
            require(!seen.empty() && seen.back().insert(value.get<std::string>()).second, "duplicate request key");
        }
        if (event == json::parse_event_t::object_end) seen.pop_back();
        return true;
    };
    json request = json::parse(raw, callback);
    keys(request, {"schema", "nonce", "rows"});
    require(request["schema"] == "native-source4096-worker-request/v1", "unknown request schema");
    require(request["nonce"].is_string() && request["nonce"].get<std::string>() == nonce, "operation nonce mismatch");
    require(request["rows"].is_array() && !request["rows"].empty() && request["rows"].size() <= 4096, "bounded source rows required");
    std::set<std::string> ids;
    for (const auto & row : request["rows"]) {
        keys(row, {"id", "source_text"});
        require(row["id"].is_string() && row["source_text"].is_string(), "literal source strings required");
        const auto id = row["id"].get<std::string>();
        const auto text = row["source_text"].get<std::string>();
        require(!id.empty() && id.size() <= 1024 && id.find('\0') == std::string::npos && ids.insert(id).second, "unique bounded source ID required");
        require(!text.empty() && text.size() <= 65536 && text.find('\0') == std::string::npos, "bounded nonempty source text required");
    }
    return request;
}
static json fd_identity(int fd) {
    struct stat stat{};
    require(fstat(fd, &stat) == 0 && S_ISREG(stat.st_mode), "owned model FD must identify a regular file");
    const int flags = fcntl(fd, F_GETFL);
    require(flags >= 0 && (flags & O_ACCMODE) == O_RDONLY, "model FD must be read-only");
    return {{"device", stat.st_dev}, {"inode", stat.st_ino}, {"bytes", stat.st_size},
            {"mtime_seconds", stat.st_mtim.tv_sec}, {"mtime_nanoseconds", stat.st_mtim.tv_nsec},
            {"ctime_seconds", stat.st_ctim.tv_sec}, {"ctime_nanoseconds", stat.st_ctim.tv_nsec}};
}
static json process_identity() {
    std::ifstream stream("/proc/self/stat");
    std::string line; std::getline(stream, line);
    const auto right = line.rfind(')');
    require(right != std::string::npos, "native process identity unavailable");
    std::istringstream fields(line.substr(right + 2));
    std::string field;
    for (int index = 3; index <= 22; ++index) require(static_cast<bool>(fields >> field), "native process birth unavailable");
    char path[4096]; const auto length = readlink("/proc/self/exe", path, sizeof(path));
    require(length > 0 && length < static_cast<ssize_t>(sizeof(path)), "native executable identity unavailable");
    return {{"pid", getpid()}, {"ppid", getppid()}, {"birth_ticks", field}, {"thread_id", static_cast<long>(syscall(SYS_gettid))}, {"executable", std::string(path, static_cast<std::size_t>(length))}};
}
static std::string emit(json value) {
    value["admitted"] = false;
    value["qualified"] = false;
    value["proof_authority"] = false;
    value["source_semantics_verified"] = false;
    value["worker_source_sha256"] = OWNER_SOURCE_SHA256;
    const auto line = value.dump() + "\n";
    std::cout << line << std::flush;
    require(std::cout.good(), "output channel failed");
    return line;
}

struct Operation {
    Clock::time_point deadline;
    std::size_t evaluated_nodes = 0;
    std::size_t nodes_without_buffer = 0;
    std::set<std::string> observed_devices;
    bool observed_non_cpu = false;
    ggml_backend_dev_t authenticated_cpu = nullptr;
    ggml_backend_buffer_type_t canonical_cpu_type = nullptr;
    std::size_t cpu_device_pointer_nodes = 0;
    std::size_t canonical_cpu_buffer_type_nodes = 0;
    std::size_t canonical_cpu_buffer_type_null_device_nodes = 0;
    std::size_t unrecognized_buffer_type_nodes = 0;
    std::string callback_error;
    std::unique_ptr<readonly_model_reclaim::Reclaimer> reclaimer;
    json reclaim_events = json::array();
    json reclaim_before_row;
    bool reclaim_active = false;
    bool stopped() const { return interrupted || !callback_error.empty() || Clock::now() >= deadline; }
    void check() const {
        if (!callback_error.empty()) throw std::runtime_error(callback_error);
        require(!stopped(), "operation interrupted or deadline expired");
    }
};
static std::string read_control(int fd, Operation & operation) {
    std::string value;
    while (true) {
        operation.check();
        pollfd descriptor{fd, POLLIN, 0};
        const int result = poll(&descriptor, 1, 200);
        if (result < 0 && errno == EINTR) continue;
        require(result >= 0, "control poll failed");
        if (!result) continue;
        require(!(descriptor.revents & (POLLERR | POLLNVAL)), "control descriptor error");
        char byte = 0; const auto size = read(fd, &byte, 1);
        if (size < 0 && errno == EINTR) continue;
        require(size == 1, "control pipe closed before complete authorization");
        value.push_back(byte);
        require(value.size() <= 2048, "control message exceeds byte limit");
        if (byte == '\n') return value;
    }
}
static json parse_control(const std::string & raw) {
    std::vector<std::set<std::string>> seen;
    auto callback = [&seen](int, json::parse_event_t event, json & value) {
        if (event == json::parse_event_t::object_start) seen.emplace_back();
        if (event == json::parse_event_t::key) require(!seen.empty() && seen.back().insert(value.get<std::string>()).second, "duplicate control key");
        if (event == json::parse_event_t::object_end) seen.pop_back();
        return true;
    };
    return json::parse(raw, callback);
}
static bool progress(float, void * opaque) { return !static_cast<Operation *>(opaque)->stopped(); }
static bool abort_decode(void * opaque) { return static_cast<Operation *>(opaque)->stopped(); }
static bool observe_node_buffer(ggml_tensor * tensor, bool ask, void * opaque) {
    auto & operation = *static_cast<Operation *>(opaque);
    if (ask) return true; // Observe actual post-compute buffers, not a caller's device label.
    if (operation.stopped()) return false;
    ++operation.evaluated_nodes;
    auto * source = tensor;
    while (source && !source->buffer && source->view_src) source = source->view_src;
    if (!source || !source->buffer) { ++operation.nodes_without_buffer; return true; }
    const auto type=ggml_backend_buffer_get_type(source->buffer);
    auto * device=ggml_backend_buft_get_device(type);
    if (device) {
        operation.observed_devices.insert(ggml_backend_dev_name(device));
        if (ggml_backend_dev_type(device)!=GGML_BACKEND_DEVICE_TYPE_CPU) operation.observed_non_cpu=true;
        else ++operation.cpu_device_pointer_nodes;
    } else if (type==operation.canonical_cpu_type && operation.authenticated_cpu
               && type==ggml_backend_cpu_buffer_type()
               && type==ggml_backend_dev_buffer_type(operation.authenticated_cpu)
               && ggml_backend_buft_is_host(type)) {
        // The pinned CPU default buffer singleton has .device=NULL. Its exact
        // registry-owned pointer identity is evidence; neither its name nor
        // host-addressability alone identifies a compute backend.
        ++operation.canonical_cpu_buffer_type_nodes;
        ++operation.canonical_cpu_buffer_type_null_device_nodes;
        operation.observed_devices.insert(ggml_backend_dev_name(operation.authenticated_cpu));
    } else ++operation.unrecognized_buffer_type_nodes;
    return !operation.observed_non_cpu;
}
static constexpr const char * CPU_OBSERVATION_POLICY="post_compute_cpu_device_or_exact_default_buffer_type";
static void bind_cpu_observer(Operation & operation,ggml_backend_dev_t cpu) {
    require(cpu && ggml_backend_dev_type(cpu)==GGML_BACKEND_DEVICE_TYPE_CPU,"authenticated CPU device required");
    require(ggml_backend_dev_count()>0,"CPU registry absent");
    for(std::size_t i=0;i<ggml_backend_dev_count();++i)
        require(ggml_backend_dev_type(ggml_backend_dev_get(i))==GGML_BACKEND_DEVICE_TYPE_CPU,"CPU-only backend registry required");
    const auto type=ggml_backend_dev_buffer_type(cpu);
    require(type==ggml_backend_cpu_buffer_type() && ggml_backend_buft_is_host(type),"exact CPU default buffer identity required");
    operation.authenticated_cpu=cpu;operation.canonical_cpu_type=type;
}
static void reset_cpu_observer(Operation & operation) {
    operation.evaluated_nodes=0;operation.nodes_without_buffer=0;operation.observed_devices.clear();operation.observed_non_cpu=false;
    operation.cpu_device_pointer_nodes=0;operation.canonical_cpu_buffer_type_nodes=0;
    operation.canonical_cpu_buffer_type_null_device_nodes=0;operation.unrecognized_buffer_type_nodes=0;
}
static bool has_cpu_observations(const Operation & operation) {
    return operation.evaluated_nodes>0 && !operation.observed_non_cpu && !operation.observed_devices.empty()
        && operation.cpu_device_pointer_nodes+operation.canonical_cpu_buffer_type_nodes>0;
}
static json cpu_observation_report(const Operation & operation) {
    require(has_cpu_observations(operation),"actual CPU operation observations missing");
    require(operation.evaluated_nodes==operation.nodes_without_buffer+operation.cpu_device_pointer_nodes
        +operation.canonical_cpu_buffer_type_nodes+operation.unrecognized_buffer_type_nodes,"CPU observation categories differ");
    return {{"policy",CPU_OBSERVATION_POLICY},{"backend_revision","571d0d540df04f25298d0e159e520d9fc62ed121"},
        {"backend_source_sha256","a96b54377e2b66732dcc5ed7ede82b6e0e873de53d515ac9fd6aa118b716bdd3"},
        {"registered_cpu_devices",{ggml_backend_dev_name(operation.authenticated_cpu)}},
        {"cpu_device_pointer_nodes",operation.cpu_device_pointer_nodes},
        {"canonical_cpu_buffer_type_nodes",operation.canonical_cpu_buffer_type_nodes},
        {"canonical_cpu_buffer_type_null_device_nodes",operation.canonical_cpu_buffer_type_null_device_nodes},
        {"unrecognized_buffer_type_nodes",operation.unrecognized_buffer_type_nodes}};
}
static json reclaim_event(const readonly_model_reclaim::Event & event) {
    return {{"rss_before_bytes",event.rss_before_bytes},{"rss_after_bytes",event.rss_after_bytes},
            {"elapsed_seconds",event.elapsed_seconds},{"syscalls",event.syscalls}};
}
static bool observe_node(ggml_tensor * tensor, bool ask, void * opaque) noexcept {
    auto & operation=*static_cast<Operation *>(opaque);
    try {
        if (!observe_node_buffer(tensor,ask,opaque)) return false;
        if (ask || !operation.reclaim_active) return true;
        require(tensor!=nullptr, "completed native tensor missing");
        const auto layer=readonly_model_reclaim::layer_index(ggml_get_name(tensor));
        if (layer>=0) {
            readonly_model_reclaim::check_next_layer(layer,operation.reclaim_events.size());
            operation.check();
            auto event=reclaim_event(operation.reclaimer->reclaim());
            event["layer"]=layer;operation.reclaim_events.push_back(event);
            operation.check();
        }
        return true;
    } catch (const std::exception & error) {
        operation.callback_error=std::string(error.what()).substr(0,256);return false;
    } catch (...) {
        operation.callback_error="unknown native observation/reclaim failure";return false;
    }
}
static json reclaim_report(const Operation & operation) {
    require(operation.reclaimer!=nullptr && operation.reclaim_events.size()==36,"all36 completed layers required");
    json intervals=json::array(),completed=json::array();
    for (const auto & value:operation.reclaimer->intervals()) intervals.push_back({
        {"start",value.start},{"end",value.end},{"offset",value.offset},{"device",value.device},
        {"inode",value.inode},{"permissions","r--s"}});
    for (int index=0;index<36;++index) {
        require(operation.reclaim_events[index]["layer"]==index,"completed layer report differs");completed.push_back(index);
    }
    return {{"policy","own_readonly_shared_madv_dontneed_after_each_completed_layer"},
            {"page_size",operation.reclaimer->page_size()},{"expected_layers",36},{"completed_layers",completed},
            {"mapping_intervals",intervals},{"before_row",operation.reclaim_before_row},
            {"layer_events",operation.reclaim_events},{"shared_filecache_eviction",false}};
}
static json describe() {
    return {{"schema", "native-source4096-worker-description/v3"}, {"modes", {"embed-authorized"}},
            {"profile", "leanstral4096:cpu1:last:l2:single-sequence:tokens512:layer-reclaim:v3"},
            {"model_loader_prefetch", false}, {"mmap_populate", false},
            {"model_map_reclaim","own_readonly_shared_madv_dontneed_after_each_completed_layer"},
            {"required_architecture","deepseek2"},{"expected_layers",36},{"shared_filecache_eviction",false},
            {"native_perf_accounting","single_reset_decode_synchronize_with_clamped_idle_counter"},
            {"cpu_buffer_observation",CPU_OBSERVATION_POLICY},
            {"cpu_extra_buffers", false}, {"authorization_required", true}, {"closing_ack_required", true},
            {"dimension", DIMENSION}, {"context_limit", LIMIT}, {"batch_limit", LIMIT}, {"ubatch_limit", LIMIT},
            {"sequence_count", 1}, {"threads", 1}, {"requested_gpu_layers", 0},
            {"add_special", true}, {"parse_special", false}, {"request_source_only", true},
            {"model_content_hash_verified_by_worker", false}, {"full_forward_executed", false}};
}

// Bounded real CPU graph control. No model FD, model path, tokenization or
// authorization is accepted; it exercises this worker's actual eval callback.
static json cpu_buffer_control() {
    Operation operation{Clock::now()+std::chrono::seconds(10)};
    ggml_backend_register(ggml_backend_cpu_reg());
    auto * cpu=ggml_backend_dev_by_type(GGML_BACKEND_DEVICE_TYPE_CPU);
    bind_cpu_observer(operation,cpu);
    auto backend=std::unique_ptr<ggml_backend,std::function<void(ggml_backend_t)>>(
        ggml_backend_cpu_init(),ggml_backend_free);
    require(backend!=nullptr && ggml_backend_is_cpu(backend.get()),"control CPU backend missing");
    require(ggml_backend_get_device(backend.get())==cpu,"control CPU device differs");
    ggml_backend_cpu_set_n_threads(backend.get(),1);
    auto ctx=std::unique_ptr<ggml_context,decltype(&ggml_free)>(
        ggml_init({1024*1024,nullptr,true}),ggml_free);
    require(ctx!=nullptr,"control tensor context missing");
    auto * left=ggml_new_tensor_1d(ctx.get(),GGML_TYPE_F32,8);
    auto * right=ggml_new_tensor_1d(ctx.get(),GGML_TYPE_F32,8);
    auto * sum=ggml_add(ctx.get(),left,right);ggml_set_name(sum,"control_add");
    auto * graph=ggml_new_graph_custom(ctx.get(),16,false);ggml_build_forward_expand(graph,sum);
    auto buffer=std::unique_ptr<ggml_backend_buffer,decltype(&ggml_backend_buffer_free)>(
        ggml_backend_alloc_ctx_tensors(ctx.get(),backend.get()),ggml_backend_buffer_free);
    require(buffer!=nullptr,"control CPU buffer missing");
    require(ggml_backend_buffer_get_type(buffer.get())==operation.canonical_cpu_type
        && ggml_backend_buft_get_device(operation.canonical_cpu_type)==nullptr,"pinned CPU singleton null-device regression differs");
    // A different, real CPU_Mapped buffer with a null device remains unknown.
    void * memory=nullptr;require(posix_memalign(&memory,64,4096)==0,"control host allocation failed");
    auto memory_owner=std::unique_ptr<void,decltype(&std::free)>(memory,std::free);
    auto mapped=std::unique_ptr<ggml_backend_buffer,decltype(&ggml_backend_buffer_free)>(
        ggml_backend_cpu_buffer_from_ptr(memory,4096),ggml_backend_buffer_free);
    require(mapped!=nullptr,"control mapped buffer missing");
    ggml_tensor mapped_probe{};mapped_probe.buffer=mapped.get();
    require(ggml_backend_buffer_get_type(mapped.get())!=operation.canonical_cpu_type
        && ggml_backend_buft_get_device(ggml_backend_buffer_get_type(mapped.get()))==nullptr,"pinned mapped buffer identity differs");
    require(observe_node_buffer(&mapped_probe,false,&operation),"unknown control classification failed");
    require(operation.unrecognized_buffer_type_nodes==1 && !has_cpu_observations(operation),"unknown buffer incorrectly proves CPU execution");
    reset_cpu_observer(operation);ggml_tensor empty_probe{};
    require(observe_node_buffer(&empty_probe,false,&operation) && operation.nodes_without_buffer==1
        && !has_cpu_observations(operation),"unbacked tensor incorrectly proves CPU execution");
    reset_cpu_observer(operation);
    ggml_backend_t backends[]={backend.get()};ggml_backend_buffer_type_t types[]={operation.canonical_cpu_type};
    auto scheduler=std::unique_ptr<ggml_backend_sched,decltype(&ggml_backend_sched_free)>(
        ggml_backend_sched_new(backends,types,1,16,false,false),ggml_backend_sched_free);
    require(scheduler!=nullptr,"control scheduler missing");
    ggml_backend_sched_set_eval_callback(scheduler.get(),observe_node,&operation);
    json repeats=json::array();
    for(int repeat=0;repeat<2;++repeat) {
        reset_cpu_observer(operation);float a[8],b[8],out[8];
        for(int j=0;j<8;++j){a[j]=float(j+repeat);b[j]=float(10+j-repeat);}
        ggml_backend_tensor_set(left,a,0,sizeof(a));ggml_backend_tensor_set(right,b,0,sizeof(b));
        require(ggml_backend_sched_graph_compute(scheduler.get(),graph)==GGML_STATUS_SUCCESS,"control add graph failed");
        ggml_backend_sched_synchronize(scheduler.get());operation.check();
        ggml_backend_tensor_get(sum,out,0,sizeof(out));
        for(int j=0;j<8;++j) require(out[j]==float(10+2*j),"control graph result differs");
        const auto observation=cpu_observation_report(operation);
        require(operation.canonical_cpu_buffer_type_null_device_nodes>0,"actual null-device callback route not exercised");
        repeats.push_back({{"index",repeat},{"output",out},{"cpu_buffer_observation",observation},
            {"post_compute_nodes_observed",operation.evaluated_nodes},
            {"nodes_without_observable_buffer",operation.nodes_without_buffer},
            {"actual_buffer_devices",operation.observed_devices}});
    }
    return {{"schema","native-source4096-cpu-buffer-control/v1"},{"complete",true},
        {"repeats",repeats},{"unknown_mapped_buffer_did_not_prove_cpu",true},
        {"unbacked_tensor_did_not_prove_cpu",true},{"same_worker_callback",true},
        {"native_cpu_graph_executed",true},{"model_opened",false},{"model_weights_loaded",false},
        {"native_tokenizer_executed",false},{"full_forward_executed",false},{"context_limit",LIMIT}};
}

static std::string model_metadata(const llama_model * model, const std::string & key, bool optional = false) {
    char value[4096];
    const int length = llama_model_meta_val_str(model, key.c_str(), value, sizeof(value));
    if (optional && length == -1) return {};
    require(length > 0 && length < static_cast<int>(sizeof(value)), "bounded native model metadata required");
    return std::string(value, static_cast<std::size_t>(length));
}
static int decimal_metadata(const std::string & value) {
    require(!value.empty() && value.size() <= 6 && std::all_of(value.begin(), value.end(), [](char c) {
        return c >= '0' && c <= '9';
    }), "positive decimal embedding metadata required");
    const int result = std::stoi(value);
    require(result > 0, "positive embedding metadata required");
    return result;
}

int main(int argc, char ** argv) {
    std::signal(SIGTERM, on_signal); std::signal(SIGINT, on_signal);
    std::signal(SIGPIPE, SIG_IGN);
    std::string nonce, mode, raw;
    json initial_fd, initial_process;
    int model_fd = -1, control_fd = -1, seconds = 0;
    std::string authorization_sha;
    bool entry_emitted = false, backend_initialized = false;
    std::size_t rows_emitted = 0, native_tokens_evaluated = 0;
    llama_model * model = nullptr;
    llama_context * context = nullptr;
    llama_batch batch{};
    bool batch_initialized = false;
    auto cleanup = [&]() {
        if (batch_initialized) { llama_batch_free(batch); batch_initialized = false; }
        if (context) { llama_free(context); context = nullptr; }
        if (model) { llama_model_free(model); model = nullptr; }
        if (backend_initialized) { llama_backend_free(); backend_initialized = false; }
    };
    try {
        // The isolated native process group must not outlive its Python owner
        // if the outer resource guardian terminates that owner abruptly.
        const pid_t owner_pid = getppid();
        require(owner_pid > 1 && prctl(PR_SET_PDEATHSIG, SIGKILL) == 0,
                "native parent-death protection unavailable");
        require(getppid() == owner_pid, "native parent changed during protection setup");
        if (argc == 2 && std::string(argv[1]) == "--describe") { emit(describe()); return 0; }
        if (argc == 2 && std::string(argv[1]) == "--cpu-buffer-control") { emit(cpu_buffer_control()); return 0; }
        require(argc == 11, "expected model-fd, control-fd, mode, nonce and deadline-seconds");
        std::set<std::string> options;
        for (int i = 1; i < argc; i += 2) {
            const std::string key(argv[i]), value(argv[i+1]);
            require(options.insert(key).second, "duplicate command option");
            if (key == "--nonce") nonce = value;
            else if (key == "--mode") mode = value;
            else if (key == "--model-fd" || key == "--control-fd" || key == "--deadline-seconds") {
                require(!value.empty() && value.size() <= 6 && std::all_of(value.begin(), value.end(), [](char c){ return c>='0' && c<='9'; }), "decimal bounded option required");
                const int integer = std::stoi(value);
                if (key == "--model-fd") model_fd = integer; else if (key == "--control-fd") control_fd = integer; else seconds = integer;
            } else require(false, "unknown command option");
        }
        require(hex64(nonce), "64 lowercase hex nonce required");
        require(mode == "embed-authorized" || mode == "validate-request", "unknown worker mode");
        require(seconds >= 1 && seconds <= 3600, "bounded operation deadline required");
        Operation operation{Clock::now() + std::chrono::seconds(seconds)};
        raw = bounded_read(std::cin); operation.check();
        const auto request = parse_request(raw, nonce);
        if (mode == "validate-request") {
            emit({{"schema","native-source4096-request-control/v1"},{"nonce",nonce},{"request_sha256",sha256(raw)},
                  {"source_rows",request["rows"].size()},{"model_opened",false},{"native_tokenizer_executed",false},{"full_forward_executed",false}});
            return 0;
        }
        require(model_fd >= 3, "owned inherited model FD required");
        require(control_fd >= 3 && control_fd != model_fd, "separate inherited control pipe required");
        struct stat control_stat{};
        require(fstat(control_fd, &control_stat) == 0 && S_ISFIFO(control_stat.st_mode)
                && (fcntl(control_fd, F_GETFL) & O_ACCMODE) == O_RDONLY, "read-only FIFO control descriptor required");
        initial_fd = fd_identity(model_fd); initial_process = process_identity();
        const auto entry_line = emit({{"schema","native-source4096-worker-entry/v2"},{"authorization_required",true},{"nonce",nonce},{"request_sha256",sha256(raw)},
              {"mode",mode},{"model_fd",model_fd},{"model_identity",initial_fd},{"process",initial_process},
              {"requested_profile",describe()},{"source_rows",request["rows"].size()},
              {"model_content_hash_verified_by_worker",false},{"model_loaded",false}});
        entry_emitted = true;
        const auto authorization_line = read_control(control_fd, operation);
        const auto authorization = parse_control(authorization_line);
        keys(authorization, {"schema","nonce","request_sha256","entry_sha256","model_sha256"});
        require(authorization["schema"] == "native-source4096-owner-authorization/v1"
                && authorization["nonce"] == nonce && authorization["request_sha256"] == sha256(raw)
                && authorization["entry_sha256"] == sha256(entry_line)
                && authorization["model_sha256"].is_string() && hex64(authorization["model_sha256"].get<std::string>()),
                "owner authorization identity differs");
        authorization_sha = sha256(authorization_line);
        require(getppid() == owner_pid && fd_identity(model_fd) == initial_fd, "authorization parent/model identity changed");
        operation.check();
        // Do not scan backend directories or load CUDA. This profile links CPU only.
        ggml_backend_register(ggml_backend_cpu_reg());
        llama_backend_init(); backend_initialized = true;
        for (std::size_t i = 0; i < ggml_backend_dev_count(); ++i)
            require(ggml_backend_dev_type(ggml_backend_dev_get(i)) == GGML_BACKEND_DEVICE_TYPE_CPU, "CPU-only backend registry required");
        auto * cpu = ggml_backend_dev_by_type(GGML_BACKEND_DEVICE_TYPE_CPU);
        require(cpu != nullptr, "native CPU backend unavailable");
        bind_cpu_observer(operation,cpu);
        ggml_backend_dev_t devices[] = {cpu, nullptr};
        auto params = llama_model_default_params();
        params.devices = devices; params.n_gpu_layers = 0;
        params.vocab_only = false;
        params.use_mmap = true; params.use_direct_io = false; params.use_mlock = false;
        params.use_extra_bufts = false; params.check_tensors = false;
        params.progress_callback = progress; params.progress_callback_user_data = &operation;
        // The parent holds/authenticates the exact read-only inode, not a mutable model filename.
        const auto model_path = std::string("/proc/self/fd/") + std::to_string(model_fd);
        model = llama_model_load_from_file(model_path.c_str(), params);
        require(model != nullptr, "native model load failed"); operation.check();
        require(fd_identity(model_fd) == initial_fd, "model identity changed during load");
        // Verify both the declared metadata and the initialized native widths.
        const auto architecture = model_metadata(model, "general.architecture");
        require(architecture.size() <= 64 && std::all_of(architecture.begin(), architecture.end(), [](char c) {
            return (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_';
        }), "bounded native architecture metadata required");
        require(architecture=="deepseek2" && decimal_metadata(model_metadata(model,"deepseek2.block_count"))==36,
                "layer-reclaim profile requires exact deepseek2 36-layer architecture");
        const auto input_key = architecture + ".embedding_length";
        const auto output_key = architecture + ".embedding_length_out";
        const int metadata_input = decimal_metadata(model_metadata(model, input_key));
        const auto output_declared = model_metadata(model, output_key, true);
        const json metadata_output = output_declared.empty() ? json(nullptr) : json(decimal_metadata(output_declared));
        require(metadata_input == DIMENSION && (metadata_output.is_null() || metadata_output == DIMENSION),
                "declared model embedding metadata is not4096");
        const int native_input = llama_model_n_embd_inp(model), native_output = llama_model_n_embd_out(model);
        if (mode == "embed-authorized") require(native_input == DIMENSION && native_output == DIMENSION, "native model width is not4096");
        const auto * vocab = llama_model_get_vocab(model); require(vocab != nullptr, "native vocabulary unavailable");
        std::vector<std::vector<llama_token>> token_rows;
        for (const auto & row : request["rows"]) {
            operation.check(); const auto text = row["source_text"].get<std::string>();
            const int needed = llama_tokenize(vocab, text.data(), static_cast<int>(text.size()), nullptr, 0, true, false);
            require(needed < 0 && -needed <= LIMIT, "native source exceeds512 tokens or tokenizer failed");
            std::vector<llama_token> tokens(static_cast<std::size_t>(-needed));
            const int count = llama_tokenize(vocab, text.data(), static_cast<int>(text.size()), tokens.data(), static_cast<int>(tokens.size()), true, false);
            require(count == static_cast<int>(tokens.size()) && count > 0, "native token count changed");
            token_rows.push_back(std::move(tokens));
        }
        json geometry = {{"native_input_dimension",mode == "embed-authorized" ? json(native_input) : json(nullptr)},
                         {"native_output_dimension",mode == "embed-authorized" ? json(native_output) : json(nullptr)},
                         {"metadata_architecture",architecture},{"metadata_embedding_length",metadata_input},
                         {"metadata_embedding_length_out",metadata_output},{"metadata_embedding_length_key",input_key},
                         {"metadata_embedding_length_out_key",output_key},
                         {"vocabulary_size",llama_vocab_n_tokens(vocab)},{"actual_context",nullptr},
                         {"actual_batch",nullptr},{"actual_ubatch",nullptr},{"actual_sequences",nullptr},
                         {"actual_pooling",nullptr},{"context_created",false}};
        if (mode == "embed-authorized") {
            auto cp = llama_context_default_params();
            cp.n_ctx = LIMIT; cp.n_batch = LIMIT; cp.n_ubatch = LIMIT; cp.n_seq_max = 1;
            cp.n_threads = 1; cp.n_threads_batch = 1; cp.embeddings = true;
            cp.pooling_type = LLAMA_POOLING_TYPE_LAST; cp.attention_type = LLAMA_ATTENTION_TYPE_CAUSAL;
            cp.offload_kqv = false; cp.op_offload = false; cp.no_perf = false;
            cp.abort_callback = abort_decode; cp.abort_callback_data = &operation;
            cp.cb_eval = observe_node; cp.cb_eval_user_data = &operation;
            context = llama_init_from_model(model, cp); require(context != nullptr, "native context construction failed"); operation.check();
            require(llama_n_ctx(context)==LIMIT && llama_n_batch(context)==LIMIT && llama_n_ubatch(context)==LIMIT
                    && llama_n_seq_max(context)==1 && llama_pooling_type(context)==LLAMA_POOLING_TYPE_LAST, "actual native geometry differs");
            geometry.update({{"actual_context",llama_n_ctx(context)},{"actual_batch",llama_n_batch(context)},
                             {"actual_ubatch",llama_n_ubatch(context)},{"actual_sequences",llama_n_seq_max(context)},
                             {"actual_pooling","last"},{"context_created",true}});
            batch = llama_batch_init(LIMIT,0,1); batch_initialized = true;
            operation.reclaimer=std::make_unique<readonly_model_reclaim::Reclaimer>(model_fd);
            operation.check();
        }
        for (std::size_t index=0; index<token_rows.size(); ++index) {
            operation.check(); const auto & row = request["rows"][index]; const auto & tokens = token_rows[index];
            json result={{"schema","native-source4096-worker-row/v2"},{"nonce",nonce},{"request_sha256",sha256(raw)},
                         {"owner_authorization_sha256",authorization_sha},{"index",index},{"id",row["id"]},{"source_sha256",sha256(row["source_text"].get<std::string>())},
                         {"token_ids",tokens},{"token_count",tokens.size()},{"add_special",true},{"parse_special",false},
                         {"truncated",false},{"chat_template_applied",false},{"geometry",geometry},
                         {"full_forward_executed",false},{"model_identity",initial_fd},{"process",initial_process}};
            if (context) {
                auto * memory = llama_get_memory(context); require(memory != nullptr, "causal native KV memory missing");
                llama_memory_clear(memory,true); llama_perf_context_reset(context);
                reset_cpu_observer(operation);
                operation.reclaim_events=json::array();operation.reclaim_active=false;
                operation.reclaim_before_row=reclaim_event(operation.reclaimer->reclaim());operation.check();
                batch.n_tokens=static_cast<int>(tokens.size());
                for (int i=0; i<batch.n_tokens; ++i) { batch.token[i]=tokens[i]; batch.pos[i]=i; batch.n_seq_id[i]=1; batch.seq_id[i][0]=0; batch.logits[i]=1; }
                operation.reclaim_active=true;
                const auto decode_status=llama_decode(context,batch);
                operation.reclaim_active=false;operation.check();
                require(decode_status==0, "native decode failed or interrupted");
                const auto reclaim_receipt=reclaim_report(operation);
                llama_synchronize(context); operation.check();
                const auto perf=llama_perf_context(context);
                const auto accounted=readonly_model_reclaim::account_single_reset_decode(
                    batch.n_tokens,perf.n_p_eval,perf.n_eval,perf.t_p_eval_ms,perf.t_eval_ms);
                const json perf_accounting={
                    {"policy","single_reset_decode_synchronize_with_clamped_idle_counter"},
                    {"backend_revision","571d0d540df04f25298d0e159e520d9fc62ed121"},
                    {"backend_context_sha256","7e5a6656cf1b4b24c6bc825d90fcab4c0aab677c53a868f51a61c742b8361c76"},
                    {"raw_n_p_eval",perf.n_p_eval},{"raw_n_eval",perf.n_eval},
                    {"raw_t_p_eval_ms",perf.t_p_eval_ms},{"raw_t_eval_ms",perf.t_eval_ms},
                    {"dispatch",accounted.dispatch},{"accounted_prompt_tokens",accounted.prompt},
                    {"accounted_single_tokens",accounted.single}};
                const auto cpu_observations=cpu_observation_report(operation);
                const float * raw_vector=llama_get_embeddings_seq(context,0); require(raw_vector!=nullptr, "native pooled output missing");
                double norm2=0.;
                for (int j=0;j<DIMENSION;++j) { require(std::isfinite(raw_vector[j]), "nonfinite native embedding"); norm2+=double(raw_vector[j])*raw_vector[j]; }
                require(std::isfinite(norm2) && norm2>0., "zero or invalid native embedding norm");
                std::vector<float> normalized(DIMENSION);
                for (int j=0;j<DIMENSION;++j) normalized[j]=static_cast<float>(raw_vector[j]/std::sqrt(norm2));
                native_tokens_evaluated+=static_cast<std::size_t>(accounted.prompt+accounted.single);
                result.update({{"cpu_buffer_observation",cpu_observations},{"native_perf_accounting",perf_accounting},{"model_map_reclaim",reclaim_receipt},{"embedding",normalized},{"full_forward_executed",true},{"normalization","l2"},
                               {"raw_output_l2_norm",std::sqrt(norm2)},{"KV_reset_before_row",true},{"synchronized_before_read",true},
                               {"native_prompt_tokens_evaluated",accounted.prompt},{"native_single_tokens_evaluated",accounted.single},
                               {"native_tokens_evaluated",accounted.prompt+accounted.single},
                               {"actual_buffer_devices",operation.observed_devices},{"post_compute_nodes_observed",operation.evaluated_nodes},
                               {"nodes_without_observable_buffer",operation.nodes_without_buffer},
                               {"device_observation_scope","post-compute tensor buffers; non-null CPU device or exact registered CPU default buffer type; offload disabled"}});
            }
            operation.check(); require(fd_identity(model_fd)==initial_fd, "model identity changed during operation");
            emit(result); ++rows_emitted;
        }
        operation.check(); require(fd_identity(model_fd)==initial_fd && process_identity()==initial_process, "closing operation identity changed");
        cleanup();
        const auto closing_line = emit({{"schema","native-source4096-worker-closing/v2"},{"owner_authorization_sha256",authorization_sha},{"closing_ack_required",true},{"nonce",nonce},{"request_sha256",sha256(raw)},
              {"mode",mode},{"complete",true},{"rows_emitted",rows_emitted},{"native_tokens_evaluated",native_tokens_evaluated},
              {"geometry",geometry},{"model_identity",fd_identity(model_fd)},{"process",process_identity()},
              {"model_and_context_freed",true},{"inherited_fd_still_parent_owned",true},
              {"full_forward_executed",true},{"model_content_hash_verified_by_worker",false}});
        const auto acknowledgement_line = read_control(control_fd, operation);
        const auto acknowledgement = parse_control(acknowledgement_line);
        keys(acknowledgement, {"schema","nonce","request_sha256","closing_sha256"});
        require(acknowledgement["schema"] == "native-source4096-owner-close-ack/v1"
                && acknowledgement["nonce"] == nonce && acknowledgement["request_sha256"] == sha256(raw)
                && acknowledgement["closing_sha256"] == sha256(closing_line), "owner closing acknowledgement differs");
        require(getppid() == owner_pid && fd_identity(model_fd) == initial_fd && process_identity() == initial_process,
                "exit operation identity changed");
        operation.check();
        emit({{"schema","native-source4096-worker-exit/v1"},{"nonce",nonce},{"request_sha256",sha256(raw)},
              {"mode",mode},{"complete",true},{"owner_authorization_sha256",authorization_sha},
              {"owner_closing_ack_sha256",sha256(acknowledgement_line)},{"model_and_context_freed",true},
              {"model_identity",fd_identity(model_fd)},{"process",process_identity()}});
        return 0;
    } catch (const std::exception & error) {
        cleanup();
        try {
            emit({{"schema","native-source4096-worker-error/v1"},{"nonce",nonce},{"complete",false},
                  {"error",std::string(error.what()).substr(0,256)},{"entry_emitted",entry_emitted},
                  {"rows_emitted",rows_emitted},{"native_tokens_evaluated",native_tokens_evaluated},
                  {"model_and_context_freed",true},{"production_cache_allowed",false}});
        } catch (...) {}
        return 2;
    }
}
