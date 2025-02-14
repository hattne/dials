from __future__ import absolute_import, division, print_function

# DIALS_ENABLE_COMMAND_LINE_COMPLETION

import copy
import logging

import iotbx.phil
from dxtbx.model.experiment_list import ExperimentList
from dials.algorithms.indexing import indexer
from dials.algorithms.indexing import DialsIndexError
from dials.array_family import flex
from dials.util.slice import slice_reflections
from dials.util.options import OptionParser
from dials.util.options import flatten_reflections
from dials.util.options import flatten_experiments
from dials.util import Sorry

logger = logging.getLogger("dials.command_line.index")


help_message = """

This program attempts to perform autoindexing on strong spots output by the
program dials.find_spots. The program is called with a "imported.expt" file
(as generated by dials.import) and a "strong.refl" file (as generated by
dials.find_spots). If one or more lattices are identified given the input
list of strong spots, then the crystal orientation and experimental geometry
are refined to minimise the differences between the observed and predicted
spot centroids. The program will output an "indexed.expt" file which
is similar to the input "imported.expt" file, but with the addition of the
crystal model(s), and an "indexed.refl" file which is similar to the input
"strong.refl" file, but with the addition of miller indices and predicted
spot centroids.

dials.index provides both one-dimensional and three-dimensional fast Fourier
transform (FFT) based methods. These can be chosen by setting the parameters
indexing.method=fft1d or indexing.method=fft3d. By default the program searches
for a primitive lattice, and then proceeds with refinement in space group P1.
If the unit_cell and space_group parameters are set, then the program will
only accept solutions which are consistent with these parameters. Space group
constraints will be enforced in refinement as appropriate.

Examples::

  dials.index imported.expt strong.refl

  dials.index imported.expt strong.refl unit_cell=37,79,79,90,90,90 space_group=P43212

  dials.index imported.expt strong.refl indexing.method=fft1d

"""


phil_scope = iotbx.phil.parse(
    """\
include scope dials.algorithms.indexing.indexer.phil_scope

indexing {

    include scope dials.algorithms.indexing.lattice_search.basis_vector_search_phil_scope

    image_range = None
      .help = "Range in images to slice a sweep. The number of arguments"
              "must be a factor of two. Each pair of arguments gives a range"
              "that follows C conventions (e.g. j0 <= j < j1) when slicing the"
              "reflections by observed centroid."
      .type = ints(size=2)
      .multiple = True

    joint_indexing = True
      .type = bool

}

include scope dials.algorithms.refinement.refiner.phil_scope

output {
  experiments = indexed.expt
    .type = path
  split_experiments = False
    .type = bool
  reflections = indexed.refl
    .type = path
  unindexed_reflections = None
    .type = path
  log = dials.index.log
    .type = str
}

""",
    process_includes=True,
)

# override default refinement parameters
phil_overrides = phil_scope.fetch(
    source=iotbx.phil.parse(
        """\
refinement {
    reflections {
        reflections_per_degree=100
    }
}
"""
    )
)

working_phil = phil_scope.fetch(sources=[phil_overrides])


def index_experiments(experiments, reflections, params, known_crystal_models=None):
    idxr = indexer.Indexer.from_parameters(
        reflections,
        experiments,
        known_crystal_models=known_crystal_models,
        params=params,
    )
    idxr.index()
    idx_refl = copy.deepcopy(idxr.refined_reflections)
    idx_refl.extend(idxr.unindexed_reflections)
    return idxr.refined_experiments, idx_refl


class Index(object):
    def __init__(self, experiments, reflections, params):

        self._params = params

        if experiments.crystals()[0] is not None:
            known_crystal_models = experiments.crystals()
        else:
            known_crystal_models = None

        if len(reflections) == 0:
            raise Sorry("No reflection lists found in input")
        elif len(reflections) == 1:
            reflections[0]["imageset_id"] = reflections[0]["id"]
        elif len(reflections) > 1:
            assert len(reflections) == len(experiments)
            for i in range(len(reflections)):
                reflections[i]["imageset_id"] = flex.int(len(reflections[i]), i)
                if i > 0:
                    reflections[0].extend(reflections[i])
        reflections = reflections[0]

        for expt in experiments:
            if (
                expt.goniometer is not None
                and expt.scan is not None
                and expt.scan.get_oscillation()[1] == 0
            ):
                expt.goniometer = None
                expt.scan = None

        if self._params.indexing.image_range:
            reflections = slice_reflections(
                reflections, self._params.indexing.image_range
            )

        if len(experiments) == 1 or self._params.indexing.joint_indexing:
            try:
                self._indexed_experiments, self._indexed_reflections = index_experiments(
                    experiments,
                    reflections,
                    copy.deepcopy(params),
                    known_crystal_models=known_crystal_models,
                )
            except DialsIndexError as e:
                raise Sorry(str(e))
        else:
            self._indexed_experiments = ExperimentList()
            self._indexed_reflections = flex.reflection_table()

            import concurrent.futures

            with concurrent.futures.ProcessPoolExecutor(
                max_workers=params.indexing.nproc
            ) as pool:
                futures = []
                for i_expt, expt in enumerate(experiments):
                    refl = reflections.select(reflections["imageset_id"] == i_expt)
                    refl["imageset_id"] = flex.size_t(len(refl), 0)
                    futures.append(
                        pool.submit(
                            index_experiments,
                            ExperimentList([expt]),
                            refl,
                            copy.deepcopy(params),
                            known_crystal_models=known_crystal_models,
                        )
                    )

                for future in concurrent.futures.as_completed(futures):
                    try:
                        idx_expts, idx_refl = future.result()
                    except Exception as e:
                        print(e)
                    else:
                        if idx_expts is None:
                            continue
                        for j_expt, _ in enumerate(idx_expts):
                            sel = idx_refl["id"] == j_expt
                            idx_refl["id"].set_selected(
                                sel, len(self._indexed_experiments) + j_expt
                            )
                        idx_refl["imageset_id"] = flex.size_t(len(idx_refl), i_expt)
                        self._indexed_reflections.extend(idx_refl)
                        self._indexed_experiments.extend(idx_expts)

    def export_experiments(self, filename):
        experiments = self._indexed_experiments
        if self._params.output.split_experiments:
            logger.info("Splitting experiments before output")

            experiments = ExperimentList([copy.deepcopy(re) for re in experiments])
        logger.info("Saving refined experiments to %s" % filename)

        assert experiments.is_consistent()
        experiments.as_file(filename)

    def export_reflections(self, filename):
        logger.info("Saving refined reflections to %s" % filename)
        self._indexed_reflections.as_msgpack_file(filename=filename)


def run(phil=working_phil, args=None):
    usage = "dials.index [options] models.expt strong.refl"

    parser = OptionParser(
        usage=usage,
        phil=phil,
        read_reflections=True,
        read_experiments=True,
        check_format=False,
        epilog=help_message,
    )

    params, options = parser.parse_args(args=args, show_diff_phil=False)

    from dials.util import log

    # Configure the logging
    log.config(verbosity=options.verbose, logfile=params.output.log)

    from dials.util.version import dials_version

    logger.info(dials_version())

    # Log the diff phil
    diff_phil = parser.diff_phil.as_str()
    if diff_phil != "":
        logger.info("The following parameters have been modified:\n")
        logger.info(diff_phil)

    experiments = flatten_experiments(params.input.experiments)
    reflections = flatten_reflections(params.input.reflections)

    if len(experiments) == 0:
        parser.print_help()
        return

    indexed = Index(experiments, reflections, params)
    indexed.export_experiments(params.output.experiments)
    indexed.export_reflections(params.output.reflections)


if __name__ == "__main__":
    run()
