import json
import os
from fractions import Fraction
from render import Renderer
from prep import VideoPrep
from media.info import LibAvVideoInfo
from region import VideoRegionUtils, RenderingSubRegion
import datetime
import tempfile
from motion.flow import Flow
from motion.interpolate import Interpolate
import pdb


class Project(object):
  '''represents a video interpolation project. describes settings of
  the project and supplies information to the renderer to complete its
  task. every project should be associated with a video.
  '''
  def __init__(self, video_path, playback_rate=Fraction(24000, 1001),
               timing_regions=None, flow_method=None, interpolate_method=None):
    self.version = '0.1'
    self.video_path = video_path
    self.playback_rate = playback_rate
    self.timing_regions = timing_regions
    if flow_method is None:
      flow_method = lambda(x, y): \
          Flow.farneback_optical_flow_ocl(x, y, 0.5, 3, 15, 3, 7, 1.5, 0)
    self.flow_method = flow_method
    if interpolate_method is None:
      interpolate_method = Interpolate.interpolate_frames
    self.interpolate_method = interpolate_method
    self.vid_info = LibAvVideoInfo(video_path)

  @classmethod
  def new(cls, video_path):
    '''returns a new blank project'''
    return cls(video_path)

  def set_timing_regions_with_string(self, region_string):
    '''a convienance function that sets the timing regions given a
    string with multiple subregions separated by a semicolon `;` char.
    example with two sub regions:
    a=[time],b=[time],fps=[rate];a=[time],b=[time],dur=[rate]
    '''
    self.timing_regions = None
    sub_regions = region_string.split(';')
    if len(sub_regions) > 0:
      self.timing_regions = []
    vid_dur_ms = self.vid_info.duration * 1000.0
    for x in sub_regions:
      # set time_b to length of video if `full` option is specified
      v = x.split(',')
      if v[0] == 'full':
        sr = RenderingSubRegion(0, vid_dur_ms)
        if len(sub_regions) > 1:
          raise ValueError(
              'more than 1 region specified after specifying a full region')
      else:
        sr = RenderingSubRegion.from_string(x)
      self.timing_regions.append(sr)
    VideoRegionUtils.validate_region_set(vid_dur_ms, self.timing_regions)

  def render_video(self, dst_path, v_scale=1.0):
    '''normalizes, renders, muxes an interpolated video, if necessary.
    when doing slow/fast motion, audio and subtitles will not be muxed
    into the final video because it wouldnt be in sync'''
    tmp_path = os.path.join(tempfile.gettempdir(), 'motionflow')
    if not os.path.exists(tmp_path):
      os.makedirs(tmp_path)
    vid_path = self.video_path
    vid_name = os.path.basename(vid_path)

    # we need relative positions before normalization
    # we'll be using it to resync frame and time points during
    # rendering as the video may change in frame count, frame rate,
    # and duration
    if self.timing_regions is not None:
      for r in self.timing_regions:
        r.sync_relative_pos_to_duration(self.vid_info.duration * 1000)

    vid_prep = VideoPrep(self.vid_info, loglevel='info')

    vid_mod_dt = os.path.getmtime(vid_path)
    vid_mod_utc = datetime.datetime.utcfromtimestamp(vid_mod_dt)
    unix_time = lambda(dt):\
        (dt - datetime.datetime.utcfromtimestamp(0)).total_seconds()

    nrm_name = '{}_{}.mp4'.format(vid_name, str(unix_time(vid_mod_utc)))
    nrm_name = nrm_name.lower()
    nrm_path = os.path.join(tmp_path, nrm_name)

    if not os.path.exists(nrm_path):
      vid_prep.normalize_for_interpolation(nrm_path, v_scale)

    nrm_name_no_ext, _ = os.path.splitext(nrm_name)
    rnd_path = os.path.join(
        tmp_path, '{}_rendered.mp4'.format(nrm_name_no_ext))

    nrm_vid_info = LibAvVideoInfo(nrm_path)
    render_task = Renderer(nrm_vid_info, self.playback_rate,
                           self.timing_regions, self.flow_method,
                           self.interpolate_method, loglevel='info')
    render_task.render(rnd_path)

    aud_path = None
    sub_path = None
    if self.timing_regions is None:
      if self.vid_info.has_audio_stream:
        aud_path = os.path.join(
            tmp_path, '{}_audio.ogg'.format(nrm_name_no_ext))
        vid_prep.extract_audio(aud_path)
      if self.vid_info.has_subtitle_stream:
        sub_path = os.path.join(
            tmp_path, '{}_subs.srt'.format(nrm_name_no_ext))
        vid_prep.extract_subtitles(sub_path)

    VideoPrep.mux_video(rnd_path, aud_path, sub_path, dst_path, 'info')

    if os.path.exists(rnd_path):
      os.remove(rnd_path)