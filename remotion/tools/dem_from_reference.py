import numpy as np, base64, sys
from PIL import Image
from scipy import ndimage as ndi
im=np.asarray(Image.open('../images/6.webp').convert('RGB')).astype(float)
X0,X1,Y0,Y1=430,1420,290,1170
crop=im[Y0:Y1,X0:X1]
elev=[3720,3404,3098,2804,2522,2251,1993,1747,1514,1294,1088,896,719,557,412,285,176,89,27]
ys=[107+28.1*i for i in range(19)]
def swatch(y):
    px=im[int(y)-11:int(y)+12,1912:1950].reshape(-1,3)
    mx=px.max(1);mn=px.min(1)
    ok=(mx>150)&(mx-mn>0 if False else True)
    px=px[(px.sum(1)>200)&(px.sum(1)<740)] if len(px)>0 else px
    v,cn=np.unique(px,axis=0,return_counts=True)
    return v[cn.argmax()]
leg=np.array([swatch(y) for y in ys]).astype(float)
print(leg.astype(int).tolist())
def chroma(a):
    mx=a.max(-1);mn=a.min(-1);c=(mx-mn)/255
    r,g,b=a[...,0],a[...,1],a[...,2]
    h=np.arctan2(np.sqrt(3)*(g-b),2*r-g-b)
    w=np.clip(c/0.3,0,1); return np.stack([w*np.cos(h),w*np.sin(h)],-1)
d=np.linalg.norm(chroma(crop)[:,:,None,:]-chroma(leg)[None,None],axis=3)
idx=d.argmin(2); dmin=d.min(2)
E=np.array(elev,float)[idx]
r,g,b=crop[...,0],crop[...,1],crop[...,2]
sea=(b>g-8)&(b>r+55)
bad=(dmin>0.6)&~sea            # labels, roads, borders
E[sea]=0
valid=~bad
# inpaint bad pixels from nearest valid
ii=ndi.distance_transform_edt(~valid,return_indices=True)[1]
E=E[tuple(ii)]
sea=sea[tuple(ii)]
E=ndi.median_filter(E,size=7)
sea=ndi.median_filter(sea.astype(np.uint8),size=7)>0
F=6
h,w=E.shape; h//=F; w//=F
Eb=E[:h*F,:w*F].reshape(h,F,w,F).mean((1,3))
Sb=sea[:h*F,:w*F].reshape(h,F,w,F).mean((1,3))>0.5
land=~Sb
# normalised smoothing over land only
num=ndi.gaussian_filter(np.where(land,Eb,0),1.1); den=ndi.gaussian_filter(land.astype(float),1.1)
Es=np.where(land,num/np.maximum(den,1e-6),0)
Es=np.where(land,np.maximum(Es,5),0)
landf=ndi.gaussian_filter(land.astype(float),1.0)
n2=ndi.gaussian_filter(np.where(land,Es,0),3.0); d2=ndi.gaussian_filter(land.astype(float),3.0)
ext=np.where(d2>1e-3,n2/np.maximum(d2,1e-3),0)
Ef=np.where(land,Es,np.minimum(ext,400))
import base64
open('dem.b64','w').write(base64.b64encode(np.clip(Ef,0,65535).astype('<u2').tobytes()).decode())
open('coast.b64','w').write(base64.b64encode(np.clip(landf*255,0,255).astype('u1').tobytes()).decode())
print(w,h,Ef.max())
