import wa_sources as W
for g,s,*_ in W.SETLIST:
    try: n=len(getattr(W,f"pages_{g}_{s}")());print(g,s,n,flush=True)
    except Exception as e: print(g,s,"ERR",repr(e)[:200],flush=True)
