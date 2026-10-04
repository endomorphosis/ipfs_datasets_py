// Linux-only, process-local RSS control for an authenticated immutable GGUF.
// This never advises the file cache and never touches anonymous memory.
#pragma once
#include <algorithm>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <fcntl.h>
#include <fstream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>
#include <vector>

namespace readonly_model_reclaim {
inline void check(bool ok, const char * why) { if (!ok) throw std::runtime_error(why); }
struct Interval {
    std::uint64_t start, end, offset, device, inode;
    bool operator==(const Interval & b) const {
        return start==b.start && end==b.end && offset==b.offset && device==b.device && inode==b.inode;
    }
};
inline std::uint64_t number(const std::string & text, int base) {
    check(!text.empty() && text.size()<=20, "bounded mapping number required");
    for (char c:text) check((c>='0' && c<='9') || (base==16 && ((c>='a' && c<='f') || (c>='A' && c<='F'))), "invalid mapping number");
    std::size_t used=0; auto result=std::stoull(text,&used,base);
    check(used==text.size(), "partial mapping number"); return result;
}
inline std::vector<Interval> parse_maps(const std::string & raw, const struct stat & identity, std::uint64_t page) {
    check(raw.size()<=8*1024*1024, "process map inventory exceeds bound");
    check(page>0 && (page&(page-1))==0 && identity.st_size>0, "invalid mapping geometry");
    const auto size=static_cast<std::uint64_t>(identity.st_size);
    check(size<=std::numeric_limits<std::uint64_t>::max()-(page-1), "model size overflow");
    const auto rounded=(size+page-1)&~(page-1);
    std::vector<Interval> result; std::istringstream stream(raw); std::string line;
    while (std::getline(stream,line)) {
        std::istringstream fields(line); std::string address,permissions,offset,device,inode;
        check(bool(fields>>address>>permissions>>offset>>device>>inode), "malformed process map row");
        const auto colon=device.find(':'); check(colon!=std::string::npos && device.find(':',colon+1)==std::string::npos,"invalid map device");
        const auto maj=number(device.substr(0,colon),16), min=number(device.substr(colon+1),16);
        const auto ino=number(inode,10);
        if (maj!=major(identity.st_dev) || min!=minor(identity.st_dev) || ino!=identity.st_ino) continue;
        check(permissions=="r--s", "model map must be read-only shared and nonexecutable");
        const auto dash=address.find('-'); check(dash!=std::string::npos && address.find('-',dash+1)==std::string::npos,"invalid map address");
        Interval current{number(address.substr(0,dash),16),number(address.substr(dash+1),16),number(offset,16),static_cast<std::uint64_t>(identity.st_dev),ino};
        check(current.start>0 && current.end>current.start && current.start%page==0 && current.end%page==0 && current.offset%page==0,"model map must be page aligned");
        check(current.offset<rounded && current.end-current.start<=rounded-current.offset,"model map exceeds held file");
        check(result.size()<128,"too many model mapping fragments"); result.push_back(current);
    }
    check(!result.empty(),"held model has no read-only shared process mappings");
    for (std::size_t i=0;i<result.size();++i) for (std::size_t j=0;j<i;++j) {
        const auto & a=result[i]; const auto & b=result[j];
        check(a.end<=b.start || b.end<=a.start,"overlapping model address ranges");
        check(a.offset+(a.end-a.start)<=b.offset || b.offset+(b.end-b.start)<=a.offset,"aliased model file ranges");
    }
    return result;
}
inline std::string maps() {
    std::ifstream stream("/proc/self/maps"); check(bool(stream),"own process maps unavailable");
    std::string raw,line; while(std::getline(stream,line)) { raw+=line;raw+='\n';check(raw.size()<=8*1024*1024,"process maps exceed bound"); }
    check(stream.eof(),"process maps read failed");return raw;
}
inline std::uint64_t rss_bytes(std::uint64_t page) {
    std::ifstream stream("/proc/self/statm");std::uint64_t virtual_pages=0,resident=0;
    check(bool(stream>>virtual_pages>>resident) && resident<=std::numeric_limits<std::uint64_t>::max()/page,"own RSS unavailable");
    return resident*page;
}
struct Event { std::uint64_t rss_before_bytes,rss_after_bytes;double elapsed_seconds;std::size_t syscalls; };
class Reclaimer {
    int fd_;struct stat identity_{};std::uint64_t page_;std::vector<Interval> intervals_;
    void identity_check() const {
        struct stat now{};const int flags=fcntl(fd_,F_GETFL);
        check(flags>=0 && (flags&O_ACCMODE)==O_RDONLY && fstat(fd_,&now)==0 && S_ISREG(now.st_mode),"read-only regular model descriptor required");
        check(now.st_dev==identity_.st_dev && now.st_ino==identity_.st_ino && now.st_size==identity_.st_size &&
              now.st_mtim.tv_sec==identity_.st_mtim.tv_sec && now.st_mtim.tv_nsec==identity_.st_mtim.tv_nsec &&
              now.st_ctim.tv_sec==identity_.st_ctim.tv_sec && now.st_ctim.tv_nsec==identity_.st_ctim.tv_nsec,"held model identity changed");
    }
public:
    explicit Reclaimer(int fd):fd_(fd),page_(static_cast<std::uint64_t>(sysconf(_SC_PAGESIZE))) {
        check(page_>0 && page_<=1024*1024 && (page_&(page_-1))==0,"invalid system page size");
        check(fstat(fd_,&identity_)==0,"model descriptor unavailable");identity_check();
        char magic[4];check(pread(fd_,magic,4,0)==4 && std::string(magic,4)=="GGUF","GGUF file magic required");
        intervals_=parse_maps(maps(),identity_,page_);
    }
    std::uint64_t page_size() const { return page_; }
    const std::vector<Interval> & intervals() const { return intervals_; }
    Event reclaim() const {
        const auto start=std::chrono::steady_clock::now();identity_check();
        check(parse_maps(maps(),identity_,page_)==intervals_,"model mapping inventory changed");
        const auto before=rss_bytes(page_);std::size_t calls=0;
        for (const auto & range:intervals_) {
            // Only this process's authenticated r--s GGUF mappings. No global cache advice.
            check(madvise(reinterpret_cast<void *>(range.start),range.end-range.start,MADV_DONTNEED)==0,"own model map reclaim failed");++calls;
        }
        identity_check();
        return Event{before,rss_bytes(page_),std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count(),calls};
    }
};
struct AccountedTokens { int prompt, single;const char * dispatch; };
inline AccountedTokens account_single_reset_decode(int tokens,int raw_prompt,int raw_single,double prompt_ms,double single_ms) {
    // Pinned llama-context.cpp resets both counters/timers, then synchronize()
    // increments one branch. perf_get_data() floors each reported count at1.
    check(tokens>=1 && tokens<=512,"bounded single-decode token count required");
    check(std::isfinite(prompt_ms) && std::isfinite(single_ms) && prompt_ms>=0. && single_ms>=0.,"finite native evaluation timings required");
    if (tokens==1) {
        check(raw_prompt==1 && raw_single==1 && prompt_ms==0. && single_ms>0.,"native single-token counter/timing dispatch differs");
        return AccountedTokens{0,1,"single_token"};
    }
    check(raw_prompt==tokens && raw_single==1 && prompt_ms>0. && single_ms==0.,"native prompt-batch counter/timing dispatch differs");
    return AccountedTokens{tokens,0,"prompt_batch"};
}
inline int layer_index(const std::string & name) {
    if(name.rfind("l_out-",0)!=0) return -1;
    const auto raw=name.substr(6);check(!raw.empty() && raw.size()<=2 && (raw=="0" || raw[0]!='0'),"invalid completed layer name");
    const auto value=number(raw,10);check(value<36,"unexpected completed layer");return static_cast<int>(value);
}
inline void check_next_layer(int actual,std::size_t completed) {
    check(completed<36 && actual==static_cast<int>(completed),"completed layer sequence differs");
}
} // namespace readonly_model_reclaim
