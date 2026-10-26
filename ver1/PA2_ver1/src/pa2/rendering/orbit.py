"""Z-up orbit camera matching PILOT Studio's Three.js OrbitControls.

CAD coordinates stay untouched. Only the interactive camera moves; video
camera paths remain controlled by SceneFrame. Pointer deltas use top-down
screen coordinates, as in the original browser viewport.
"""
import math


def _cross(a,b):
    return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])


def _unit(v):
    length=math.sqrt(sum(x*x for x in v)) or 1.0
    return tuple(x/length for x in v)


class OrbitCamera:
    def __init__(self,camera):
        self.camera=camera
        self.min_distance=0.02; self.max_distance=1e6
        self.reset_motion()

    def reset_motion(self):
        self.theta_delta=0.0; self.phi_delta=0.0; self.pan_delta=[0.0,0.0,0.0]

    def rotate(self,dx,dy,height):
        self.theta_delta-=2*math.pi*dx/max(height,1)
        self.phi_delta-=2*math.pi*dy/max(height,1)

    def pan(self,dx,dy,height):
        camera=self.camera
        forward=_unit(tuple(t-p for p,t in zip(camera.GetPosition(),camera.GetFocalPoint())))
        right=_unit(_cross(forward,camera.GetViewUp())); up=_cross(right,forward)
        half_height=camera.GetParallelScale() if camera.GetParallelProjection() else camera.GetDistance()*math.tan(math.radians(camera.GetViewAngle())/2)
        scale=2*half_height/max(height,1)
        for i in range(3):self.pan_delta[i]+=(-dx*right[i]+dy*up[i])*scale

    def zoom(self,steps):
        camera=self.camera
        if camera.GetParallelProjection():
            camera.SetParallelScale(max(1e-9,camera.GetParallelScale()*0.95**steps))
        else:
            center=camera.GetFocalPoint(); offset=tuple(p-t for p,t in zip(camera.GetPosition(),center))
            distance=camera.GetDistance()
            target=max(self.min_distance,min(self.max_distance,distance*0.95**steps))
            if distance>1e-12:camera.SetPosition(*(t+x*target/distance for t,x in zip(center,offset)))

    def step(self):
        camera=self.camera
        center=camera.GetFocalPoint(); offset=tuple(p-t for p,t in zip(camera.GetPosition(),center))
        radius=max(camera.GetDistance(),1e-12)
        theta=math.atan2(offset[0],-offset[1])+self.theta_delta
        phi=math.acos(max(-1.0,min(1.0,offset[2]/radius)))+self.phi_delta
        phi=max(1e-6,min(math.pi-1e-6,phi))
        center=tuple(t+d for t,d in zip(center,self.pan_delta))
        camera.SetFocalPoint(*center)
        camera.SetPosition(center[0]+radius*math.sin(phi)*math.sin(theta),
                           center[1]-radius*math.sin(phi)*math.cos(theta),
                           center[2]+radius*math.cos(phi))
        camera.SetViewUp(0,0,1)
        self.reset_motion()
        return False
