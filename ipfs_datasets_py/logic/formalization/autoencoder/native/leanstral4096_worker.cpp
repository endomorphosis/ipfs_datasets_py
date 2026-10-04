// Source-only native feature extraction. This is not a semantic/proof verifier.
// The parent must authenticate this binary, native libraries and model contents,
// admit resources, keep the model FD open, and require a successful closing row.
#include "llama.h"
#include "ggml-backend.h"
#include "ggml-cpu.h"
#include "json.hpp"
#include <openssl/sha.h>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstdint>
#include <fcntl.h>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
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
    return {{"pid", getpid()}, {"ppid", getppid()}, {"birth_ticks", field}, {"executable", std::string(path, static_cast<std::size_t>(length))}};
}
static void emit(json value) {
    value["admitted"] = false;
    value["qualified"] = false;
    value["proof_authority"] = false;
    value["source_semantics_verified"] = false;
    value["worker_source_sha256"] = OWNER_SOURCE_SHA256;
    std::cout << value.dump() << '\n' << std::flush;
    require(std::cout.good(), "output channel failed");
}

struct Operation {
    Clock::time_point deadline;
    std::size_t evaluated_nodes = 0;
    std::size_t nodes_without_buffer = 0;
    std::set<std::string> observed_devices;
    bool observed_non_cpu = false;
    bool stopped() const { return interrupted || Clock::now() >= deadline; }
    void check() const { require(!stopped(), "operation interrupted or deadline expired"); }
};
static bool progress(float, void * opaque) { return !static_cast<Operation *>(opaque)->stopped(); }
static bool abort_decode(void * opaque) { return static_cast<Operation *>(opaque)->stopped(); }
static bool observe_node(ggml_tensor * tensor, bool ask, void * opaque) {
    auto & operation = *static_cast<Operation *>(opaque);
    if (ask) return true; // Observe actual post-compute buffers, not a caller's device label.
    if (operation.stopped()) return false;
    ++operation.evaluated_nodes;
    auto * source = tensor;
    while (source && !source->buffer && source->view_src) source = source->view_src;
    if (!source || !source->buffer) { ++operation.nodes_without_buffer; return true; }
    auto * device = ggml_backend_buft_get_device(ggml_backend_buffer_get_type(source->buffer));
    if (!device) { ++operation.nodes_without_buffer; return true; }
    operation.observed_devices.insert(ggml_backend_dev_name(device));
    if (ggml_backend_dev_type(device) != GGML_BACKEND_DEVICE_TYPE_CPU) operation.observed_non_cpu = true;
    return !operation.observed_non_cpu;
}
static json describe() {
    return {{"schema", "native-source4096-worker-description/v1"}, {"modes", {"vocab", "embed"}},
            {"profile", "leanstral4096:cpu1:last:l2:single-sequence:tokens512:v1"},
            {"dimension", DIMENSION}, {"context_limit", LIMIT}, {"batch_limit", LIMIT}, {"ubatch_limit", LIMIT},
            {"sequence_count", 1}, {"threads", 1}, {"requested_gpu_layers", 0},
            {"add_special", true}, {"parse_special", false}, {"request_source_only", true},
            {"model_content_hash_verified_by_worker", false}, {"full_forward_executed", false}};
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
    int model_fd = -1, seconds = 0;
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
        require(argc == 9, "expected model-fd, mode, nonce and deadline-seconds");
        std::set<std::string> options;
        for (int i = 1; i < argc; i += 2) {
            const std::string key(argv[i]), value(argv[i+1]);
            require(options.insert(key).second, "duplicate command option");
            if (key == "--nonce") nonce = value;
            else if (key == "--mode") mode = value;
            else if (key == "--model-fd" || key == "--deadline-seconds") {
                require(!value.empty() && value.size() <= 6 && std::all_of(value.begin(), value.end(), [](char c){ return c>='0' && c<='9'; }), "decimal bounded option required");
                const int integer = std::stoi(value);
                if (key == "--model-fd") model_fd = integer; else seconds = integer;
            } else require(false, "unknown command option");
        }
        require(hex64(nonce), "64 lowercase hex nonce required");
        require(mode == "vocab" || mode == "embed" || mode == "validate-request", "unknown worker mode");
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
        initial_fd = fd_identity(model_fd); initial_process = process_identity();
        emit({{"schema","native-source4096-worker-entry/v1"},{"nonce",nonce},{"request_sha256",sha256(raw)},
              {"mode",mode},{"model_fd",model_fd},{"model_identity",initial_fd},{"process",initial_process},
              {"requested_profile",describe()},{"source_rows",request["rows"].size()},
              {"model_content_hash_verified_by_worker",false},{"model_loaded",false}});
        entry_emitted = true;
        // Do not scan backend directories or load CUDA. This profile links CPU only.
        ggml_backend_register(ggml_backend_cpu_reg());
        llama_backend_init(); backend_initialized = true;
        for (std::size_t i = 0; i < ggml_backend_dev_count(); ++i)
            require(ggml_backend_dev_type(ggml_backend_dev_get(i)) == GGML_BACKEND_DEVICE_TYPE_CPU, "CPU-only backend registry required");
        auto * cpu = ggml_backend_dev_by_type(GGML_BACKEND_DEVICE_TYPE_CPU);
        require(cpu != nullptr, "native CPU backend unavailable");
        ggml_backend_dev_t devices[] = {cpu, nullptr};
        auto params = llama_model_default_params();
        params.devices = devices; params.n_gpu_layers = 0;
        params.vocab_only = mode == "vocab";
        params.use_mmap = true; params.use_direct_io = false; params.use_mlock = false;
        params.use_extra_bufts = false; params.check_tensors = false;
        params.progress_callback = progress; params.progress_callback_user_data = &operation;
        // The parent holds/authenticates the exact read-only inode, not a mutable model filename.
        const auto model_path = std::string("/proc/self/fd/") + std::to_string(model_fd);
        model = llama_model_load_from_file(model_path.c_str(), params);
        require(model != nullptr, "native model load failed"); operation.check();
        require(fd_identity(model_fd) == initial_fd, "model identity changed during load");
        // vocab_only intentionally skips native hyperparameter initialization.
        // Report explicit GGUF declarations here, never pretend those are an
        // executed or initialized native input/output width.
        const auto architecture = model_metadata(model, "general.architecture");
        require(architecture.size() <= 64 && std::all_of(architecture.begin(), architecture.end(), [](char c) {
            return (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_';
        }), "bounded native architecture metadata required");
        const auto input_key = architecture + ".embedding_length";
        const auto output_key = architecture + ".embedding_length_out";
        const int metadata_input = decimal_metadata(model_metadata(model, input_key));
        const auto output_declared = model_metadata(model, output_key, true);
        const json metadata_output = output_declared.empty() ? json(nullptr) : json(decimal_metadata(output_declared));
        require(metadata_input == DIMENSION && (metadata_output.is_null() || metadata_output == DIMENSION),
                "declared model embedding metadata is not4096");
        const int native_input = llama_model_n_embd_inp(model), native_output = llama_model_n_embd_out(model);
        if (mode == "embed") require(native_input == DIMENSION && native_output == DIMENSION, "native model width is not4096");
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
        json geometry = {{"native_input_dimension",mode == "embed" ? json(native_input) : json(nullptr)},
                         {"native_output_dimension",mode == "embed" ? json(native_output) : json(nullptr)},
                         {"metadata_architecture",architecture},{"metadata_embedding_length",metadata_input},
                         {"metadata_embedding_length_out",metadata_output},{"metadata_embedding_length_key",input_key},
                         {"metadata_embedding_length_out_key",output_key},
                         {"vocabulary_size",llama_vocab_n_tokens(vocab)},{"actual_context",nullptr},
                         {"actual_batch",nullptr},{"actual_ubatch",nullptr},{"actual_sequences",nullptr},
                         {"actual_pooling",nullptr},{"context_created",false}};
        if (mode == "embed") {
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
        }
        for (std::size_t index=0; index<token_rows.size(); ++index) {
            operation.check(); const auto & row = request["rows"][index]; const auto & tokens = token_rows[index];
            json result={{"schema","native-source4096-worker-row/v1"},{"nonce",nonce},{"request_sha256",sha256(raw)},
                         {"index",index},{"id",row["id"]},{"source_sha256",sha256(row["source_text"].get<std::string>())},
                         {"token_ids",tokens},{"token_count",tokens.size()},{"add_special",true},{"parse_special",false},
                         {"truncated",false},{"chat_template_applied",false},{"geometry",geometry},
                         {"full_forward_executed",false},{"model_identity",initial_fd},{"process",initial_process}};
            if (context) {
                auto * memory = llama_get_memory(context); require(memory != nullptr, "causal native KV memory missing");
                llama_memory_clear(memory,true); llama_perf_context_reset(context);
                operation.evaluated_nodes=0; operation.nodes_without_buffer=0; operation.observed_devices.clear(); operation.observed_non_cpu=false;
                batch.n_tokens=static_cast<int>(tokens.size());
                for (int i=0; i<batch.n_tokens; ++i) { batch.token[i]=tokens[i]; batch.pos[i]=i; batch.n_seq_id[i]=1; batch.seq_id[i][0]=0; batch.logits[i]=1; }
                require(llama_decode(context,batch)==0, "native decode failed or interrupted");
                llama_synchronize(context); operation.check();
                const auto perf=llama_perf_context(context);
                require(perf.n_p_eval>=0 && perf.n_eval>=0 && perf.n_p_eval+perf.n_eval==batch.n_tokens, "native evaluated-token count differs");
                require(operation.evaluated_nodes>0 && !operation.observed_non_cpu && !operation.observed_devices.empty(), "actual CPU operation observations missing");
                const float * raw_vector=llama_get_embeddings_seq(context,0); require(raw_vector!=nullptr, "native pooled output missing");
                double norm2=0.;
                for (int j=0;j<DIMENSION;++j) { require(std::isfinite(raw_vector[j]), "nonfinite native embedding"); norm2+=double(raw_vector[j])*raw_vector[j]; }
                require(std::isfinite(norm2) && norm2>0., "zero or invalid native embedding norm");
                std::vector<float> normalized(DIMENSION);
                for (int j=0;j<DIMENSION;++j) normalized[j]=static_cast<float>(raw_vector[j]/std::sqrt(norm2));
                native_tokens_evaluated+=static_cast<std::size_t>(perf.n_p_eval+perf.n_eval);
                result.update({{"embedding",normalized},{"full_forward_executed",true},{"normalization","l2"},
                               {"raw_output_l2_norm",std::sqrt(norm2)},{"KV_reset_before_row",true},{"synchronized_before_read",true},
                               {"native_prompt_tokens_evaluated",perf.n_p_eval},{"native_single_tokens_evaluated",perf.n_eval},
                               {"native_tokens_evaluated",perf.n_p_eval+perf.n_eval},
                               {"actual_buffer_devices",operation.observed_devices},{"post_compute_nodes_observed",operation.evaluated_nodes},
                               {"nodes_without_observable_buffer",operation.nodes_without_buffer},
                               {"device_observation_scope","post-compute tensor buffers; CPU-only registered backend and offload disabled"}});
            }
            operation.check(); require(fd_identity(model_fd)==initial_fd, "model identity changed during operation");
            emit(result); ++rows_emitted;
        }
        operation.check(); require(fd_identity(model_fd)==initial_fd && process_identity()==initial_process, "closing operation identity changed");
        cleanup();
        emit({{"schema","native-source4096-worker-closing/v1"},{"nonce",nonce},{"request_sha256",sha256(raw)},
              {"mode",mode},{"complete",true},{"rows_emitted",rows_emitted},{"native_tokens_evaluated",native_tokens_evaluated},
              {"geometry",geometry},{"model_identity",fd_identity(model_fd)},{"process",process_identity()},
              {"model_and_context_freed",true},{"inherited_fd_still_parent_owned",true},
              {"full_forward_executed",mode=="embed"},{"model_content_hash_verified_by_worker",false}});
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
