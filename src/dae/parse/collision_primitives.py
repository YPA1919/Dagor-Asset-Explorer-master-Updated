"""Triangle previews for analytic collision shapes (24 sides, 8 steps/hemisphere)."""
from math import sin, cos, pi, sqrt, isfinite

def box_mesh(bounds):
    lo, hi = bounds[:3], bounds[3:]
    verts = [(x,y,z) for z in (lo[2],hi[2]) for y in (lo[1],hi[1]) for x in (lo[0],hi[0])]
    faces = [(0,2,1),(1,2,3),(4,5,6),(5,7,6),(0,1,4),(1,5,4),(2,6,3),(3,6,7),(0,4,2),(2,4,6),(1,3,5),(3,7,5)]
    return verts, faces

def capsule_mesh(a, b, radius, sides=24, steps=8):
    if not all(isfinite(x) for x in (*a,*b,radius)) or radius < 0:
        raise ValueError('Invalid collision capsule')
    delta = [b[i]-a[i] for i in range(3)]
    length = sqrt(sum(x*x for x in delta))
    axis = [x/length for x in delta] if length else [0,0,1]
    ref = [1,0,0] if abs(axis[0]) < .9 else [0,1,0]
    u = [axis[1]*ref[2]-axis[2]*ref[1],axis[2]*ref[0]-axis[0]*ref[2],axis[0]*ref[1]-axis[1]*ref[0]]
    n = sqrt(sum(x*x for x in u));u = [x/n for x in u]
    v = [axis[1]*u[2]-axis[2]*u[1],axis[2]*u[0]-axis[0]*u[2],axis[0]*u[1]-axis[1]*u[0]]
    verts = [tuple(a[i]-radius*axis[i] for i in range(3))]
    rings = [(a,-pi/2+j*pi/(2*steps)) for j in range(1,steps+1)]
    rings += [(b,j*pi/(2*steps)) for j in range(0 if length else 1,steps)]
    for center,angle in rings:
        for k in range(sides):
            theta=2*pi*k/sides
            verts.append(tuple(center[i]+radius*(sin(angle)*axis[i]+cos(angle)*(cos(theta)*u[i]+sin(theta)*v[i])) for i in range(3)))
    top=len(verts);verts.append(tuple(b[i]+radius*axis[i] for i in range(3)))
    faces=[]
    for k in range(sides):
        nxt=(k+1)%sides
        faces.append((0,1+nxt,1+k))
        for j in range(len(rings)-1):
            x=1+j*sides;y=x+sides
            faces.extend([(x+k,x+nxt,y+k),(x+nxt,y+nxt,y+k)])
        last=1+(len(rings)-1)*sides
        faces.append((last+k,last+nxt,top))
    return verts,faces
