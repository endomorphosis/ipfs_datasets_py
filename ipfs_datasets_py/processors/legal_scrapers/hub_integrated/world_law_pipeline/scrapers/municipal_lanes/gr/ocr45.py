import os, subprocess, json, time, shutil, sys, glob
os.environ["OMP_THREAD_LIMIT"]="2"
def memavail():
    for l in open("/proc/meminfo"):
        if l.startswith("MemAvailable"): return int(l.split()[1])/2**20
def guard():
    while True:
        d=shutil.disk_usage("/").free/2**30; m=memavail()
        if d>=15 and m>=4.5: return
        print(f"PAUSE disk={d:.1f}G mem={m:.1f}G",flush=True); time.sleep(60)
log=open("ocr_log.jsonl","a")
for pdf in sorted(glob.glob("pdf/*.pdf")):
    ada=os.path.basename(pdf)[:-4]; out=f"ocr/{ada}.txt"
    if os.path.exists(out): continue
    n=int([l for l in subprocess.run(["pdfinfo",pdf],capture_output=True,text=True).stdout.splitlines() if l.startswith("Pages")][0].split()[1])
    pages=[]; err=None; t0=time.time()
    for p in range(1,n+1):
        guard()
        r=subprocess.run(["pdftoppm","-r","300","-gray","-png","-f",str(p),"-l",str(p),"-singlefile",pdf,"scratch/page"],capture_output=True)
        if r.returncode: err=f"pdftoppm p{p}: {r.stderr.decode()[:200]}"; break
        r=subprocess.run(["tesseract","scratch/page.png","stdout","-l","ell+eng","--psm","3"],capture_output=True,timeout=900)
        if r.returncode: err=f"tesseract p{p}: {r.stderr.decode()[:200]}"; break
        pages.append(r.stdout.decode("utf-8","replace"))
    rec={"ada":ada,"pages":n,"secs":round(time.time()-t0)}
    if err: rec.update(ok=False,error=err)
    else:
        open(out,"w",encoding="utf-8").write("\f".join(pages)); rec.update(ok=True,chars=sum(map(len,pages)))
    log.write(json.dumps(rec,ensure_ascii=False)+"\n"); log.flush(); print(rec,flush=True)
print("ALLDONE",flush=True)
