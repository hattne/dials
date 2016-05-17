#
# profile_model.py
#
#  Copyright (C) 2013 Diamond Light Source
#
#  Author: James Parkhurst
#
#  This code is distributed under the BSD license, a copy of which is
#  included in the root directory of this package.

from __future__ import division
from libtbx.phil import parse
from dials.model.experiment.profile import ProfileModelIface

phil_scope = parse('''

  gaussian_rs
  {
    scan_varying = False
        .type = bool
        .help = "Calculate a scan varying model"

    min_spots
      .help = "if (total_reflections > overall or reflections_per_degree >"
              "per_degree) then do the profile modelling."
    {
      overall = 100
        .type = int(value_min=0)
        .help = "The minimum number of spots needed to do the profile modelling"

      per_degree = 50
        .type = int(value_min=0)
        .help = "The minimum number of spots needed to do the profile modelling"
    }

    filter
    {
      min_zeta = 0.05
        .type = float
        .help = "Filter reflections by min zeta"
    }

    fitting {

      scan_step = 5
        .type = float
        .help = "Space between profiles in degrees"

      grid_size = 5
        .type = int
        .help = "The size of the profile grid."

      threshold = 0.02
        .type = float
        .help = "The threshold to use in reference profile"

      grid_method = single *regular_grid circular_grid
        .type = choice
        .help = "Select the profile grid method"

      fit_method = *reciprocal_space detector_space
        .type = choice
        .help = "The fitting method"

    }
  }

''')


class Model(ProfileModelIface):

  def __init__(self,
               params,
               n_sigma,
               sigma_b,
               sigma_m,
               deg=False):
    ''' Initialise with the parameters. '''
    from math import pi
    from dials.array_family import flex
    self.params = params
    self._n_sigma = n_sigma
    if deg:
      self._sigma_b = sigma_b * pi / 180.0
      self._sigma_m = sigma_m * pi / 180.0
    else:
      self._sigma_b = sigma_b
      self._sigma_m = sigma_m
    assert(self._n_sigma > 0)
    if isinstance(self._sigma_b, flex.double):
      self._scan_varying = True
    else:
      self._scan_varying = False
    if self._scan_varying:
      assert(self._sigma_b.all_gt(0))
      assert(self._sigma_m.all_gt(0))
      assert(len(self._sigma_b) == len(self._sigma_m))
    else:
      assert(self._sigma_b > 0)
      assert(self._sigma_m >= 0)
      assert(self._n_sigma > 0)

  @classmethod
  def from_dict(cls, obj):
    ''' Convert the profile model from a dictionary. '''
    if obj['__id__'] != "gaussian_rs":
      raise RuntimeError('expected __id__ gaussian_rs, got %s' % obj['__id__'])
    n_sigma = obj['n_sigma']
    sigma_b = obj['sigma_b']
    sigma_m = obj['sigma_m']
    if isinstance(sigma_b, list):
      assert(len(sigma_b) == len(sigma_m))
      sigma_b = flex.double(sigma_b)
      sigma_m = flex.double(sigma_m)
    return cls(None, n_sigma, sigma_b, sigma_m, deg=True)

  def to_dict(self):
    ''' Convert the model to a dictionary. '''
    n_sigma = self.n_sigma()
    if self._scan_varying:
      sigma_b = list(self.sigma_b(deg=True))
      sigma_m = list(self.sigma_m(deg=True))
    else:
      sigma_b = self.sigma_b(deg=True)
      sigma_m = self.sigma_m(deg=True)
    return {
      '__id__' : 'gaussian_rs',
      'n_sigma' : n_sigma,
      'sigma_b' : sigma_b,
      'sigma_m' : sigma_m
    }

  def sigma_b(self, index=None, deg=True):
    ''' Return sigma_b. '''
    from math import pi
    if index is None:
      sigma_b = self._sigma_b
    else:
      sigma_b = self._sigma_b[index]
    if deg:
      return sigma_b * 180.0 / pi
    return sigma_b

  def sigma_m(self, index=None, deg=True):
    ''' Return sigma_m. '''
    from math import pi
    if index is None:
      sigma_m = self._sigma_m
    else:
      sigma_m = self._sigma_m[index]
    if deg:
      return sigma_m * 180.0 / pi
    return sigma_m

  def n_sigma(self):
    ''' The number of sigmas. '''
    return self._n_sigma

  def delta_b(self, index=None, deg=True):
    ''' Return delta_b. '''
    return self.sigma_b(index, deg) * self.n_sigma()

  def delta_m(self, index=None, deg=True):
    ''' Return delta_m. '''
    return self.sigma_m(index, deg) * self.n_sigma()

  def is_scan_varying(self):
    ''' Return whether scan varying. '''
    return self._scan_varying

  def num_scan_points(self):
    ''' Return number of scan points. '''
    if self._scan_varying:
      assert(len(self._sigma_m) == len(self._sigma_b))
      return len(self._sigma_m)
    return 1

  @classmethod
  def create(cls,
             params,
             reflections,
             crystal,
             beam,
             detector,
             goniometer=None,
             scan=None):
    '''
    Create the profile model from data.

    :param params: The phil parameters
    :param reflections: The reflections
    :param crystal: The crystal model
    :param beam: The beam model
    :param detector: The detector model
    :param goniometer: The goniometer model
    :param scan: The scan model
    :return: An instance of the profile model

    '''
    from dials.algorithms.profile_model.gaussian_rs.calculator \
      import ProfileModelCalculator
    from dials.algorithms.profile_model.gaussian_rs.calculator \
      import ScanVaryingProfileModelCalculator

    # Check the number of spots
    if not len(reflections) > params.gaussian_rs.min_spots.overall:
      if scan is not None:
        num_degrees = scan.get_num_images() * scan.get_oscillation()[1]
        spots_per_degree = len(reflections) / num_degrees
        if not spots_per_degree > params.gaussian_rs.min_spots.per_degree:
          raise RuntimeError('''
            Too few reflections for profile modelling:
              expected > %d per degree, got %d or > %d in total, got %d
            ''' % (
              params.gaussian_rs.min_spots.per_degree,
              spots_per_degree,
              params.gaussian_rs.min_spots.overall,
              len(reflections)))
      else:
        raise RuntimeError('''
          Too few reflections for profile modelling:
            expected > %d, got %d
          ''' % (
            params.gaussian_rs.min_spots.overall,
            len(reflections)))

    if not params.gaussian_rs.scan_varying:
      Calculator = ProfileModelCalculator
    else:
      Calculator = ScanVaryingProfileModelCalculator
    calculator = Calculator(
      reflections,
      crystal,
      beam,
      detector,
      goniometer,
      scan,
      params.gaussian_rs.filter.min_zeta)
    return cls(
      params=params,
      n_sigma=3.0,
      sigma_b=calculator.sigma_b(),
      sigma_m=calculator.sigma_m())

  def predict_reflections(self,
                          imageset,
                          crystal,
                          beam,
                          detector,
                          goniometer=None,
                          scan=None,
                          dmin=None,
                          dmax=None,
                          margin=1,
                          force_static=False,
                          **kwargs):
    '''
    Given an experiment, predict the reflections.

    :param crystal: The crystal model
    :param beam: The beam model
    :param detector: The detector model
    :param goniometer: The goniometer model
    :param scan: The scan model

    '''
    from dxtbx.model.experiment.experiment_list import Experiment
    from dials.algorithms.spot_prediction.reflection_predictor \
      import ReflectionPredictor
    predict = ReflectionPredictor(
      Experiment(
        imageset=imageset,
        crystal=crystal,
        beam=beam,
        detector=detector,
        goniometer=goniometer,
        scan=scan),
      dmin=dmin,
      dmax=dmax,
      margin=margin,
      force_static=force_static)
    return predict()

  def compute_partiality(self,
                         reflections,
                         crystal,
                         beam,
                         detector,
                         goniometer=None,
                         scan=None,
                         **kwargs):
    '''
    Given an experiment and list of reflections, compute the partiality of the
    reflections

    :param reflections: The reflection table
    :param crystal: The crystal model
    :param beam: The beam model
    :param detector: The detector model
    :param goniometer: The goniometer model
    :param scan: The scan model

    '''
    from dials.algorithms.profile_model.gaussian_rs import PartialityCalculator
    from dials.algorithms.profile_model.gaussian_rs import PartialityCalculator

    # Create the partiality calculator
    calculate = PartialityCalculator(
      crystal,
      beam,
      detector,
      goniometer,
      scan,
      self._sigma_m)

    # Compute the partiality
    partiality = calculate(
      reflections['s1'],
      reflections['xyzcal.px'].parts()[2],
      reflections['bbox'])

    # Return the partiality
    return partiality

  def compute_bbox(self,
                   reflections,
                   crystal,
                   beam,
                   detector,
                   goniometer=None,
                   scan=None,
                   sigma_b_multiplier=2.0,
                   **kwargs):
    ''' Given an experiment and list of reflections, compute the
    bounding box of the reflections on the detector (and image frames).

    :param reflections: The reflection table
    :param crystal: The crystal model
    :param beam: The beam model
    :param detector: The detector model
    :param goniometer: The goniometer model
    :param scan: The scan model

    '''
    from dials.algorithms.profile_model.gaussian_rs import BBoxCalculator

    # Check the input
    assert(sigma_b_multiplier >= 1.0)

    # Compute the size in reciprocal space. Add a sigma_b multiplier to enlarge
    # the region of background in the shoebox
    delta_b = self._n_sigma * self._sigma_b * sigma_b_multiplier
    delta_m = self._n_sigma * self._sigma_m

    # Create the bbox calculator
    calculate = BBoxCalculator(
      crystal,
      beam,
      detector,
      goniometer,
      scan,
      delta_b,
      delta_m)

    # Calculate the bounding boxes of all the reflections
    bbox = calculate(
      reflections['s1'],
      reflections['xyzcal.px'].parts()[2],
      reflections['panel'])

    # Return the bounding boxes
    return bbox

  def compute_mask(self,
                   reflections,
                   crystal,
                   beam,
                   detector,
                   goniometer=None,
                   scan=None,
                   image_volume=None,
                   **kwargs):
    '''
    Given an experiment and list of reflections, compute the
    foreground/background mask of the reflections.

    :param reflections: The reflection table
    :param crystal: The crystal model
    :param beam: The beam model
    :param detector: The detector model
    :param goniometer: The goniometer model
    :param scan: The scan model

    '''
    from dials.algorithms.profile_model.gaussian_rs import MaskCalculator

    # Compute the size in reciprocal space. Add a sigma_b multiplier to enlarge
    # the region of background in the shoebox
    delta_b = self._n_sigma * self._sigma_b
    delta_m = self._n_sigma * self._sigma_m

    # Create the mask calculator
    mask_foreground = MaskCalculator(
      crystal,
      beam,
      detector,
      goniometer,
      scan,
      delta_b,
      delta_m)

    # Mask the foreground region
    if image_volume is None:
      return mask_foreground(
        reflections['shoebox'],
        reflections['s1'],
        reflections['xyzcal.px'].parts()[2],
        reflections['panel'])
    else:
      return mask_foreground(
        image_volume,
        reflections['bbox'],
        reflections['s1'],
        reflections['xyzcal.px'].parts()[2],
        reflections['panel'])

  def fitting_class(self):
    '''
    Get the profile fitting algorithm associated with this profile model

    :return: The profile fitting class

    '''
    from dials.array_family import flex

    # Check input
    if self._scan_varying:
      if not self.sigma_m().all_gt(0):
        return None
    else:
      if self.sigma_m() <= 0:
        return None

    # Define a function to create the fitting class
    def wrapper(experiment):
      from dials.algorithms.profile_model.gaussian_rs import GaussianRSProfileModeller
      from math import ceil

      # Return if no scan or gonio
      if (experiment.scan is None or
          experiment.goniometer is None or
          experiment.scan.get_oscillation()[1] == 0):
        return None

      # Compute the scan step
      phi0, phi1 = experiment.scan.get_oscillation_range(deg=True)
      assert(phi1 > phi0)
      phi_range = phi1 - phi0
      num_scan_points = int(ceil(phi_range / self.params.gaussian_rs.fitting.scan_step))
      assert(num_scan_points > 0)

      # Create the grid method
      GridMethod = GaussianRSProfileModeller.GridMethod
      FitMethod = GaussianRSProfileModeller.FitMethod
      grid_method = int(GridMethod.names[self.params.gaussian_rs.fitting.grid_method].real)
      fit_method = int(FitMethod.names[self.params.gaussian_rs.fitting.fit_method].real)

      if self._scan_varying:
        sigma_b = flex.mean(self.sigma_b(deg=False))
        sigma_m = flex.mean(self.sigma_m(deg=False))
      else:
        sigma_b = self.sigma_b(deg=False)
        sigma_m = self.sigma_m(deg=False)

      # Create the modeller
      return GaussianRSProfileModeller(
        experiment.beam,
        experiment.detector,
        experiment.goniometer,
        experiment.scan,
        sigma_b,
        sigma_m,
        self.n_sigma(),
        self.params.gaussian_rs.fitting.grid_size,
        num_scan_points,
        self.params.gaussian_rs.fitting.threshold,
        grid_method,
        fit_method)

    # Return the wrapper function
    return wrapper
