import numpy as np, base64, heapq, json
w,h=165,146
a=np.frombuffer(base64.b64decode(open('dem.b64').read()),'<u2').reshape(h,w).astype(float)
gy,gx=np.gradient(a)
slope=np.hypot(gx,gy)
cost=1+a/120+slope/40
cost[a==0]=1e6
def dij(s,t,pen=None):
    D=np.full((h,w),1e18);D[s[1],s[0]]=0;pq=[(0,s)];prev={}
    while pq:
        d,(x,y)=heapq.heappop(pq)
        if (x,y)==t:break
        if d>D[y,x]:continue
        for dx in(-1,0,1):
            for dy in(-1,0,1):
                if not(dx or dy):continue
                nx,ny=x+dx,y+dy
                if 0<=nx<w and 0<=ny<h:
                    c=cost[ny,nx]*(1.414 if dx and dy else 1)+(pen[ny,nx] if pen is not None else 0)
                    if d+c<D[ny,nx]:
                        D[ny,nx]=d+c;prev[(nx,ny)]=(x,y);heapq.heappush(pq,(d+c,(nx,ny)))
    p=[t]
    while p[-1]!=s:p.append(prev[p[-1]])
    return p[::-1]
def loop(P):
    path=[];pen=np.zeros((h,w))
    for i in range(len(P)):
        s,t=P[i],P[(i+1)%len(P)]
        seg=dij(s,t,pen)
        for x,y in seg: pen[max(0,y-2):y+3,max(0,x-2):x+3]+=3
        path+=seg[:-1]
    return np.array(path,float)
def keys(path,n=16):
    path=np.vstack([path,path[0]])
    d=np.r_[0,np.cumsum(np.hypot(*np.diff(path,axis=0).T))]
    # smooth
    k=np.linspace(0,d[-1],n,endpoint=False)
    xs=np.interp(k,d,path[:,0]);ys=np.interp(k,d,path[:,1])
    return [[round(float(x),1),round(float(y),1)] for x,y in zip(xs,ys)],d[-1]
out={}
for name,P in {'A':[(78,40),(62,58),(50,44),(64,30)],'B':[(62,76),(48,88),(38,78),(52,68)]}.items():
    print(name,[a[y,x] for x,y in P])
    k,L=keys(loop(P)); out[name]=k; print(name,'len',L)
json.dump(out,open('routes.json','w'))
print(json.dumps(out))
