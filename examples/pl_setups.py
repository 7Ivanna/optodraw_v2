import numpy as np
import drawsvg as draw
from optodraw import *
from optodraw.core.transform import Vec3
from optodraw.core.component import Component, Group

# Robust Vec3 math patches
def _vec3_add(self, other):
    if isinstance(other, Vec3):
        return Vec3(self.x + other.x, self.y + other.y, self.z + other.z)
    if isinstance(other, (tuple, list, np.ndarray)):
        ox = other[0]
        oy = other[1]
        oz = other[2] if len(other) > 2 else 0.0
        return Vec3(self.x + ox, self.y + oy, self.z + oz)
    raise TypeError(f"Cannot add {type(other)} to Vec3")

def _vec3_sub(self, other):
    if isinstance(other, Vec3):
        return Vec3(self.x - other.x, self.y - other.y, self.z - other.z)
    if isinstance(other, (tuple, list, np.ndarray)):
        ox = other[0]
        oy = other[1]
        oz = other[2] if len(other) > 2 else 0.0
        return Vec3(self.x - ox, self.y - oy, self.z - oz)
    raise TypeError(f"Cannot subtract {type(other)} from Vec3")

def _vec3_getitem(self, index):
    if index == 0:
        return self.x
    elif index == 1:
        return self.y
    elif index == 2:
        return self.z
    raise IndexError("Vec3 index out of range")

Vec3.__getitem__ = _vec3_getitem
Vec3.__len__ = lambda self: 3
Vec3.__add__ = _vec3_add
Vec3.__sub__ = _vec3_sub
Vec3.origin = property(lambda self: self)

# Legacy Compatibility Patches
Component.center = property(lambda self: self.transform.center)
Component.real_frame = property(lambda self: self.transform.position)
Component.real_center = property(lambda self: self.transform.center)
Component.real_end_ray = property(lambda self: self.transform.position)
Component.end_width = property(lambda self: getattr(self, "aperture", 10.0))

class Transformable(Group):
    def __init__(self, center=(0, 0), angle=0, **kwargs):
        super().__init__(**kwargs)
        self.transform = Transform.from_2d(center[0], center[1], angle)

    def append(self, child):
        return self.add(child)

    def extend(self, children):
        for child in children:
            self.add(child)

class ImageCutter(Razor):
    def __init__(self, center=(0, 0), angle=0, blade_pos=0.0, **kwargs):
        super().__init__(center=center, angle=angle, blade_pos=blade_pos, **kwargs)

class Focusing(FocusingBeam):
    def __init__(self, anchor1, anchor2, width1=5.0, width2=0.0, wavelength=633.0, **kwargs):
        wavelength_val = wavelength
        if isinstance(wavelength, str):
            wavelength_val = 633.0
        kwargs.pop("offset1", None)
        kwargs.pop("offset2", None)
        super().__init__(anchor1, anchor2, width1=width1, width2=width2, wavelength=wavelength_val, **kwargs)

wls = {
    'IR': 1550.0,
    'pump': 532.0
}


def cell_test(fname='temp.svg'):
  scene = Scene(title="Test Setup", width=50, height=100, platform="free_space")
  scene.add(Grid(pitch=10))
  scene.add(Sample(in_cryostat=True))

  d = scene.render_svg()
  d.save_svg(fname)
  return d


def cell_scratch(fname='temp.svg'):
  scene = Scene(title="Scratch Setup", width=100, height=100, platform="free_space")
  scene.add(Grid(pitch=10))
  lens1 = Lens(center=[0,0])
  lens2 = Lens(center=[10,0], angle=45)
  mir = Mirror(center=[-10,0], angle=45)
  las = Laser(center=[-10, 10], angle=90, wavelength=633.0)
  lamp = Lamp(center=[20, 10], angle=90)
  beam = Beam(las, mir, lens2, [20, -5], width=0.5)

  scene.add(beam)
  scene.add(mir)
  scene.add(las)
  scene.add(lens1)
  scene.add(lens2)
  scene.add(lamp)
  scene.add(Objective(center=[0, -20]))

  d = scene.render_svg()
  d.save_svg(fname)
  return d


def cell_complicated(blade_pos=-1, show=None, offset_collection=True, fname='temp.svg'):
  if show is None:
    show = ['inputs', 'outputs']

  scene = Scene(title="Active PL", width=120, height=120, platform="free_space")
  scene.add(Grid(pitch=5, width=120, height=120))

  element_list = []
  beam_list = []

  # Pump and telescope assembly
  pump_assy = Transformable(center=[-20, -25], angle=-90)
  pump_laser = Laser(center=[0,0], wavelength=wls['pump'])
  pump_assy.append(pump_laser)
  pump_assy.append(Lens(center=[5, 0]))
  pump_assy.append(Lens(center=[15, 0]))
  element_list.append(pump_assy)

  # Illuminator and camera
  microscope_assy = Transformable(center=[-10, 15], angle=0)
  illuminator = Lamp(angle=90)
  camera = Camera(center=[5, -5], angle=180)
  microscope_assy.extend([illuminator, camera])
  lamp_bs = BeamSplitter(center=[0, -5], angle=135)
  microscope_assy.extend([lamp_bs])
  element_list.append(microscope_assy)

  # Image combiner
  im_bs = BeamSplitter(center=[microscope_assy.center[0], 0], angle=45)
  element_list.append(im_bs)

  # Periscope
  periscope_assy = Transformable(center=[10, 0])
  periscope_assy.append(Mirror(center=[0,0], angle=135))
  periscope_assy.append(Mirror(center=[0,20], angle=-45))
  periscope_assy.append(Mirror(center=[20,20], angle=-135))
  objective = Objective(center=[20, 10], angle=90)
  periscope_assy.append(objective)
  element_list.append(periscope_assy)

  # Sample
  sample = Sample(center=(np.array(periscope_assy.center)
                          + np.array(periscope_assy.children[-1].center)
                          + np.array([0,-32])),
                  in_cryostat=True,
                  angle=90)
  element_list.append(sample)

  # PL combiner
  pl_bs = BeamSplitter(center=[pump_assy.center[0], 0], angle=-45)
  element_list.append(pl_bs)

  # Cutter and mirror to cutter
  mirror_to_cutter = Mirror(center=[pump_assy.center[0] - 10, 0], angle=45)
  element_list.append(mirror_to_cutter)
  cutter = ImageCutter(blade_pos=blade_pos, center=[mirror_to_cutter.center[0], 10], angle=-90)
  element_list.append(cutter)
  mirror_to_spct = Mirror(center=cutter.real_end_ray + (0,10), angle=-45)
  element_list.append(mirror_to_spct)

  # Spectrometer
  spct_assy = Transformable(center=[mirror_to_spct.real_frame.x + 10, mirror_to_spct.real_frame.y], angle=180)
  spct_lens = Lens()
  spct = Spectrometer(center=[-5, 0])
  spct_assy.extend([spct, spct_lens])
  element_list.append(spct_assy)

  # Beams
  if 'inputs' in show:
    beam_list.append(Beam(illuminator, im_bs, *periscope_assy.children, width=3, wavelength=wls['pump']))

  if 'outputs' in show:
    beam_list.append(Beam(*periscope_assy.children[::-1], im_bs, lamp_bs, camera,
                          wavelength=illuminator.wavelength if hasattr(illuminator, 'wavelength') else 633.0, width=3))

  if 'outputs' in show:
    beam_list.append(Beam(cutter, mirror_to_cutter, *periscope_assy.children, width=2, wavelength=wls['IR']))
    beam_list.append(Beam(cutter.real_end_ray, mirror_to_spct, spct_lens, width=2, wavelength=wls['IR']))

    chip_offsets = [0, 2] if offset_collection else [0]
    border_offsets = []
    if offset_collection: border_offsets.append(2)
    if blade_pos < 0: border_offsets.append(0)

    for offset in chip_offsets:
      beam_list.append(Focusing(sample, objective.real_end_ray, 0, objective.end_width,
                                wavelength=wls['IR'], opacity=.8))
    for offset in border_offsets:
      beam_list.append(Focusing(spct_lens.real_frame, spct.real_frame, 2, 0, opacity=0.8, wavelength=wls['IR']))

  if 'inputs' in show:
    beam_list.append(Beam(pump_laser, pl_bs, *periscope_assy.children, wavelength=wls['pump']))
    beam_list.append(Beam(pump_laser, pl_bs, im_bs, wavelength=wls['pump']))
    beam_list.append(Focusing(sample, objective.real_end_ray, 0, objective.end_width/4, opacity=1, wavelength=wls['pump']))

  if 'outputs' in show:
    beam_list.append(Beam(*periscope_assy.children[::-1], im_bs, lamp_bs, camera,
                          wavelength=wls['pump']))

  # Add elements and beams to scene
  for item in element_list:
    scene.add(item)
  for beam in beam_list:
    scene.add(beam)

  # Fiducials
  fiducial_list = []
  Z_stage = draw.Path(stroke_width=.5, stroke='black', fill='none', stroke_dasharray='1,1')
  Z_stage.M(objective.real_end_ray.x - 8, objective.real_end_ray.y - 20)
  Z_stage.h(16)
  Z_stage.V(14)
  Z_stage.h(-16)
  Z_stage.V(-12)
  Z_stage.h(-19)
  Z_stage.V(objective.real_end_ray.y - 20)
  Z_stage.Z()
  fiducial_list.append(Z_stage)

  d = scene.render_svg()
  for fid in fiducial_list:
    d.append(fid)

  d.save_svg(fname)
  return d


def cell_ofc(offset_collection=True, fname='temp.svg'):
  scene = Scene(title="OFC Setup", width=120, height=120, platform="free_space")

  element_list = []
  beam_list = []

  # Pump and dichroic
  pump_laser = Laser(center=[-20, 5], angle=0, wavelength=wls['pump'])
  element_list.append(pump_laser)

  # PL combiner
  pl_bs = BeamSplitter(center=[0, pump_laser.center[1]], angle=45)
  element_list.append(pl_bs)

  # Objective
  objective = Objective(center=[0, 0], angle=90)
  element_list.append(objective)

  # Sample
  sample = Sample(center=(np.array(objective.center)
                          + np.array(objective.center)
                          + np.array([0,-26])),
                  in_cryostat=True,
                  angle=90)
  element_list.append(sample)

  # beam split off to IR camera
  ircam_assy = Transformable(center=[objective.center[0], pl_bs.center[1] + 15], angle=0)
  ir_bs = BeamSplitter(center=[0,0], angle=45)
  ir_lens = Lens(center=[-12, 0])
  ir_cam = Camera(center=[-20, 0])
  ircam_assy.extend([ir_bs, ir_lens, ir_cam])
  element_list.append(ircam_assy)

  mirror_to_spct = Mirror(center=[objective.center[0], ircam_assy.center[1] + 20], angle=-135)
  element_list.append(mirror_to_spct)

  # Spectrometer
  spct_assy = Transformable(center=[mirror_to_spct.real_frame.x - 7, mirror_to_spct.real_frame.y], angle=0)
  spct_lens = Lens()
  spct = Spectrometer(center=[-8, 0])
  spct_assy.extend([spct, spct_lens])
  element_list.append(spct_assy)

  ## The focusing two point things ##
  chip_offsets = [0]
  slit_offsets = [0]
  if offset_collection:
      chip_offsets.append(2)
      slit_offsets.append(-2)

  # from the chip
  for offset in chip_offsets:
      beam_list.append(Focusing(sample, objective.real_end_ray, 0, objective.end_width,
                                wavelength=wls['IR'], opacity=.8))
  # to the spectrometer
  for offset in slit_offsets:
      beam_list.append(Focusing(spct_lens.real_frame, spct.real_frame, 2, 0, opacity=0.8, wavelength=wls['IR']))

  # to the IR camera
  for offset in slit_offsets:
      beam_list.append(Focusing(ir_lens.real_frame, ir_cam.real_frame, 2, 0, opacity=0.8, wavelength=wls['IR']))

  # Collimated beams
  # PL
  beam_list.append(Beam(objective, mirror_to_spct, spct_lens, width=2, wavelength=wls['IR']))
  beam_list.append(Beam(objective, ir_bs, ir_lens, width=2, wavelength=wls['IR']))

  # Pump
  beam_list.append(Beam(pump_laser, pl_bs, objective, wavelength=wls['pump']))
  beam_list.append(Focusing(sample, objective.real_end_ray, 0, objective.end_width/4, opacity=1, wavelength=wls['pump']))

  for item in element_list:
      scene.add(item)
  for beam in beam_list:
      scene.add(beam)

  d = scene.render_svg()
  d.save_svg(fname)
  return d


def cell_iop(blade_pos=0.5, offset_collection=True, fname='iop_blocking.svg'):
  scene = Scene(title="IOP Setup", width=120, height=120, platform="free_space")

  element_list = []
  beam_list = []

  # Pump and dichroic
  pump_laser = Laser(center=[-15, 5], angle=0, wavelength=wls['pump'])
  element_list.append(pump_laser)
  pl_bs = BeamSplitter(center=[0, pump_laser.center[1]], angle=45)
  element_list.append(pl_bs)

  # Objective
  objective = Objective(center=[0, 0], angle=90)
  element_list.append(objective)

  # Sample
  sample = Sample(center=(np.array(objective.center)
                          + np.array(objective.center)
                          + np.array([0,-26])),
                  in_cryostat=True,
                  angle=90)
  element_list.append(sample)

  # Cutter
  cutter = ImageCutter(blade_pos=blade_pos, center=[pl_bs.center[0], pl_bs.center[1] + 10], angle=-90)
  element_list.append(cutter)

  # IR camera
  ircam_assy = Transformable(center=cutter.real_end_ray + (0, 10), angle=0)
  ir_bs = BeamSplitter(center=[0,0], angle=45)
  ir_lens = Lens(center=[-7, 0])
  ir_cam = Camera(center=[-15, 0])
  ircam_assy.extend([ir_bs, ir_lens, ir_cam])
  element_list.append(ircam_assy)

  # Spectrometer
  mirror_to_spct = Mirror(center=[objective.center[0], ircam_assy.center[1] + 15],
                          angle=-135 if blade_pos < 0 else -145)
  element_list.append(mirror_to_spct)
  spct_assy = Transformable(center=[mirror_to_spct.real_frame.x - 7, mirror_to_spct.real_frame.y], angle=0)
  spct_lens = Lens()
  spct = Spectrometer(center=[-8, 0])
  spct_assy.extend([spct, spct_lens])
  element_list.append(spct_assy)

  ## The focusing two point things ##
  chip_offsets = []
  chip_offsets.append(0)
  slit_offsets = []
  IRcam_offsets = []
  offset_in_lens = spct_lens.real_frame + ([0,0] if blade_pos < 0 else [0,1])
  if blade_pos < 0:
      slit_offsets.append(0)
      IRcam_offsets.append(0)
  if offset_collection:
      chip_offsets.append(2)
      IRcam_offsets.append(-2)
      slit_offsets.append(-2 if blade_pos < 0 else 0)

  # from the chip
  for offset in chip_offsets:
      beam_list.append(Focusing(sample, objective.real_end_ray, 0, objective.end_width,
                                wavelength=wls['IR'], opacity=.8))
  # to the spectrometer
  for offset in slit_offsets:
      beam_list.append(Focusing(offset_in_lens, spct.real_frame, 2, 0, opacity=0.8, wavelength=wls['IR']))

  # to the IR camera
  for offset in IRcam_offsets:
      beam_list.append(Focusing(ir_lens.real_frame, ir_cam.real_frame, 2, 0, opacity=0.8, wavelength=wls['IR']))

  # Collimated beams
  # PL
  beam_list.append(Beam(objective, cutter, width=2, wavelength=wls['IR']))
  beam_list.append(Beam(cutter.real_end_ray, ir_bs, ir_lens, width=2, wavelength=wls['IR']))
  beam_list.append(Beam(cutter.real_end_ray, mirror_to_spct, width=2, wavelength=wls['IR']))
  beam_list.append(Beam(mirror_to_spct, offset_in_lens, width=2, wavelength=wls['IR']))

  # Pump
  beam_list.append(Beam(pump_laser, pl_bs, objective, wavelength=wls['pump']))
  beam_list.append(Focusing(sample, objective.real_end_ray, 0, objective.end_width/4, opacity=1, wavelength=wls['pump']))

  for item in element_list:
      scene.add(item)
  for beam in beam_list:
      scene.add(beam)

  d = scene.render_svg()
  d.save_svg(fname)
  return d


if __name__ == '__main__':
  import os
  os.makedirs('examples/output', exist_ok=True)
  cell_test(fname='examples/output/simple_test.svg')
  cell_scratch(fname='examples/output/basic_scratch.svg')
  cell_complicated(blade_pos=-1, show=['inputs', 'outputs'], offset_collection=True, fname='examples/output/pl_all_pass.svg')
  cell_complicated(blade_pos=0, show=['inputs', 'outputs'], offset_collection=False, fname='examples/output/pl_all_block.svg')
  cell_ofc(offset_collection=True, fname='examples/output/ofc_setup.svg')
  cell_iop(blade_pos=0.5, offset_collection=True, fname='examples/output/iop_blocking.svg')
  print("All examples generated successfully!")
