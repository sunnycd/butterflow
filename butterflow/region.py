import re
from fractions import Fraction


class VideoRegionUtils(object):
  @staticmethod
  def validate_region_set(vid_duration_ms, regions):
    '''a set of regions are valid if and only if for each region, x, in
    the set, x is within bounds [0,vid_duration] and x does not
    intersect any other region and x is not equal to any other region'''
    # this is an n^2 algo that can be improved, but the number of
    # of regions to be processed is so small, its not really worth it
    in_bounds = lambda(x): x.time_a >= 0 and x.time_b <= vid_duration_ms
    for x in regions:
      if not in_bounds(x):
        raise RuntimeError(
            'region [{},{}] not in bounds [0,{}]'.
            format(x.time_a, x.time_b, vid_duration_ms))
      for y in regions:
        if x is not y:
          if x.intersects(y):
            raise RuntimeError(
                'region {} interesects existing region {}'.format(x, y))
          if x == y:
            raise RuntimeError(
                'region {} is the same as region {}'.format(x, y))
    return True

  @staticmethod
  def time_string_to_ms(time):
    value_error = ValueError('invalid region string: {}'.format(time))

    time_match = re.match(
        r'^([\d]{2}):([\d]{2}):([\d]{2})(\.[\d]{0,3})$', time)
    if time_match is None:
      raise value_error

    matches = time_match.groups()
    if len(matches) is not 4:
      raise value_error
    for m in matches:
      if m is None:
        raise value_error

    h = float(matches[0])
    m = float(matches[1])
    s = float(matches[2])
    ms = float(matches[3])
    return ((h * 60 * 60) + (m * 60) + s + ms) * 1000


class VideoSubRegion(object):
  '''describes a subregion in a video'''
  def __init__(self, ta, tb, fa=None, fb=None):
    self._time_a = ta
    self._time_b = tb
    self.validate(ta, tb)
    self.frame_a = fa
    self.frame_b = fb
    self.relative_pos_a = None
    self.relative_pos_b = None

  def validate(self, a, b):
    if a < 0 or a > b:
      raise ValueError('a ({}) must be nonzero and <= b ({})'.format(a, b))
    if b < a:
      raise ValueError('b ({}) must be >= than a ({})'.format(a, b))

  @property
  def time_a(self):
    return self._time_a

  @time_a.setter
  def time_a(self, val):
    self.validate(val, self.time_b)
    self._time_a = val

  @property
  def time_b(self):
    return self._time_b

  @time_b.setter
  def time_b(self, val):
    self.validate(self.time_a, val)
    self._time_b = val

  def intersects(self, other):
    '''returns if regions intersect each other, that is if either ends
    fall within each others ranges.
    '''
    if self == other:
      return True
    if self.time_a > other.time_a and self.time_a < other.time_b:
      return True
    if self.time_b > other.time_a and self.time_b < other.time_b:
      return True
    if self.frame_a > other.frame_a and self.frame_a < other.frame_a:
      return True
    if self.frame_b > other.frame_a and self.frame_b < other.frame_b:
      return True
    return False

  def __lt__(self, other):
    return self.time_a < other.time_a and self.time_b <= other.time_a

  def __gt__(self, other):
    return self.time_a >= other.time_b and self.time_b > other.time_b

  def __eq__(self, other):
    return self.time_a == other.time_a and self.time_b == other.time_b

  def __le__(self, other):
    return NotImplemented

  def __ge__(self, other):
    return NotImplemented

  def __ne__(self, other):
      return self.time_a != other.time_a and self.time_b != other.time_b


class RenderingSubRegion(VideoSubRegion):
  '''rendering sub region that contains target rate or time'''
  def __init__(self, time_a, time_b):
    super(RenderingSubRegion, self).__init__(time_a, time_b)
    self.target_rate = None
    self.target_duration = None

  @classmethod
  def from_rate(cls, time_a, time_b, rate):
    '''rate can be a fraction'''
    obj = cls(time_a, time_b)
    obj.target_rate = rate
    return obj

  @classmethod
  def from_duration(cls, time_a, time_b, duration):
    obj = cls(time_a, time_b)
    obj.target_duration = duration
    return obj

  @classmethod
  def from_string(cls, string):
    '''returns a sub region given a formatted string
    the two formats:
    a=[time],b=[time],fps=[num/den]
    a=[time],b=[time],dur=[duration in seconds]
    where time should be in the form hh:mm:ss.xxx
    '''
    v = string.split(',')
    a_part = v[0].split('=')[1]
    b_part = v[1].split('=')[1]
    t_part_l = v[2].split('=')[0]
    t_part_r = v[2].split('=')[1]

    time_a = VideoRegionUtils.time_string_to_ms(a_part)
    time_b = VideoRegionUtils.time_string_to_ms(b_part)

    fps = None
    dur = None

    if t_part_l == 'fps':
      if '/' in t_part_r:
        v = t_part_r.split('/')
        fps = Fraction(int(v[0]), int(v[1]))
      else:
        fps = float(t_part_r)
    if t_part_l == 'dur':
      dur = float(t_part_r) * 1000

    obj = cls(time_a, time_b)
    obj.target_rate = fps
    obj.target_duration = dur
    return obj

  def sync_frame_points_with_fps(self, fps):
    '''updates frame points relative to the video's fps'''
    fps = float(fps)
    self.frame_a = int(((self.time_a / 1000) * fps) + 0.5)
    self.frame_b = int(((self.time_b / 1000) * fps) + 0.5)

  def sync_relative_pos_to_frames(self, num_frames_in_video):
    '''sets relative positioning using number of frames in a video and
    the current frame points
    '''
    if num_frames_in_video == 0:
      raise ValueError('num frames must be non-zero')
    if num_frames_in_video < self.frame_b:
      raise ValueError(
          'num frames ({}) must be greater than frame B ({})'.
          format(num_frames_in_video, self.frame_b))
    self.relative_pos_a = self.frame_a * 1.0 / num_frames_in_video
    self.relative_pos_b = self.frame_b * 1.0 / num_frames_in_video

  def sync_relative_pos_to_duration(self, duration_ms_of_video):
    '''sets relative positioning using duration in milliseconds of a
    video and the current time points
    '''
    if duration_ms_of_video == 0:
      raise ValueError('duration must be non-zero')
    if duration_ms_of_video < self.time_b:
      raise ValueError(
          'duration ({}) must be greater than time B ({})'.
          format(duration_ms_of_video, self.time_b))
    self.relative_pos_a = self.time_a * 1.0 / duration_ms_of_video
    self.relative_pos_b = self.time_b * 1.0 / duration_ms_of_video

  def resync_points(self, a_rel, b_rel, duration_ms, num_frames):
    '''update frame and time points relative to a video with duration
    in milliseconds and number of frames
    '''
    self.time_a = a_rel * duration_ms
    self.time_b = b_rel * duration_ms
    self.frame_a = int(a_rel * num_frames + 0.5)
    self.frame_b = int(b_rel * num_frames + 0.5)

  def __str__(self):
    return '<time=[{},{}], rate={}, duration={}>'.format(
        self.time_a, self.time_b, self.target_rate, self.target_duration)