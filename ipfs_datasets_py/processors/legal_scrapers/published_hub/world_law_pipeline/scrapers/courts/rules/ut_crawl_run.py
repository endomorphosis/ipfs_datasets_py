import ut_sources as U,sys
for t,*_ in U.TYPES:
    n=len(getattr(U,"pages_"+t)());print(t,n,flush=True)
