# -----------------------------------------------------------------------------
#  Copyright (C) 2020 Keith Roberts

#  Distributed under the terms of the GNU General Public License. You should
#  have received a copy of the license along with this program. If not,
#  see <http://www.gnu.org/licenses/>.
# -----------------------------------------------------------------------------
import numpy as np
import scipy.spatial as spspatial
import time

from . import utils as mutils

try:
    from .cpp import c_cgal
except ImportError:
    print(
        "CGAL-based mesh generation utilities not found, you want to install"
        " CGAL for enhanced performance and parallel capabilities"
        " Using qhull instead...",
        flush=True,
    )
    method = "qhull"


class MeshGenerator:  # noqa: C901
    """
    MeshGenerator: using sizng function and signed distance field build a mesh

    Usage
    -------
    >>> obj = MeshGenerator(MeshSizeFunction_obj,method='qhull')

    Parameters
    -------
        MeshSizeFunction_obj: self-explantatory
                        **kwargs
        method: verbose name of mesh generation method to use  (default=qhull) or cgal
    -------


    Returns
    -------
        A mesh object
    -------


    Example
    ------
    >>> msh = MeshSizeFunction(ef)
    -------

    """

    def __init__(self, SizingFunction, method="qhull"):
        self.SizingFunction = SizingFunction
        self.method = method

    # SETTERS AND GETTERS
    @property
    def SizingFunction(self):
        return self.__SizingFunction

    @SizingFunction.setter
    def SizingFunction(self, value):
        self.__SizingFunction = value

    @property
    def method(self):
        return self.__method

    @method.setter
    def method(self, value):
        self.__method = value

    ### PUBLIC METHODS ###
    def build(  # noqa: ignore=C901
        self, pfix=None, max_iter=10, nscreen=5, plot=False, seed=None
    ):
        """
        Interface to either DistMesh2D/3D mesh generator using signed distance functions.
        User has option to use either qhull or cgal for Del. retriangulation.

        Usage
        -----
        >>> p, t = build(self, pfix=None, max_iter=20, plot=False, seed=None)

        Parameters
        ----------
        pfix: points that you wish you constrain (default==None)
        max_iter: maximum number of iterations (default==20)
        nscreen: output to screen nscreen (default==5)
        plot: Visualize incremental meshes (default==False)
        seed: Random seed to ensure results are deterministic

        Returns
        -------
        p:         Point positions (np, dim)
        t:         Triangle indices (nt, dim+1)
        """

        _ef = self.SizingFunction
        fd = _ef.fd
        fh = _ef.fh
        h0 = _ef.hmin
        bbox = _ef.bbox
        _method = self.method

        # set random seed to ensure deterministic results for mesh generator
        if seed is not None:
            print("Setting psuedo-random number seed to " + str(seed))
            np.random.seed(seed)

        if plot:
            import matplotlib.pyplot as plt

        dim = int(len(bbox) / 2)
        bbox = np.array(bbox).reshape(-1, 2)

        ptol = 0.001
        ttol = 0.1
        L0mult = 1 + 0.4 / 2 ** (dim - 1)
        deltat = 0.1
        geps = 1e-1 * h0
        deps = np.sqrt(np.finfo(np.double).eps) * h0

        if pfix is not None:
            pfix = np.array(pfix, dtype="d")
            nfix = len(pfix)
        else:
            pfix = np.empty((0, dim))
            nfix = 0

        # 1. Create initial distribution in bounding box (equilateral triangles)
        p = np.mgrid[tuple(slice(min, max + h0, h0) for min, max in bbox)]
        p = p.reshape(dim, -1).T

        # 2. Remove points outside the region, apply the rejection method
        p = p[fd(p) < geps]  # Keep only d<0 points
        r0 = fh(p)
        p = np.vstack(
            (pfix, p[np.random.rand(p.shape[0]) < r0.min() ** dim / r0 ** dim])
        )
        N = p.shape[0]

        count = 0
        pold = float("inf")  # For first iteration

        print("Commencing mesh generation with %d vertices." % N, flush=True)

        while True:

            # 3. Retriangulation by the Delaunay algorithm
            def dist(p1, p2):
                return np.sqrt(((p1 - p2) ** 2).sum(1))

            start = time.time()
            if (dist(p, pold) / h0).max() > ttol:  # Any large movement?
                # Make sure all points are unique
                p = np.unique(p, axis=0)
                pold = p.copy()  # Save current positions
                if _method == "qhull":
                    t = spspatial.Delaunay(p).vertices  # List of triangles
                elif _method == "cgal":
                    if dim == 2:
                        t = c_cgal.delaunay2(p[:, 0], p[:, 1])  # List of triangles
                    elif dim == 3:
                        t = c_cgal.delaunay3(
                            p[:, 0], p[:, 1], p[:, 2]
                        )  # List of triangles

                pmid = p[t].sum(1) / (dim + 1)  # Compute centroids
                t = t[fd(pmid) < -geps]  # Keep interior triangles

                # 4. Describe each bar by a unique pair of nodes
                if dim == 2:
                    bars = np.concatenate([t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]])
                elif dim == 3:
                    bars = np.concatenate(
                        [
                            t[:, [0, 1]],
                            t[:, [1, 2]],
                            t[:, [2, 0]],
                            t[:, [0, 3]],
                            t[:, [1, 3]],
                            t[:, [2, 3]],
                        ]
                    )
                bars = np.sort(bars, axis=1)
                bars = mutils.unique_rows(bars)  # Bars as node pairs

                # 5. Graphical output of the current mesh
                if plot:
                    if count % nscreen == 0:
                        if dim == 2:
                            plt.triplot(p[:, 0], p[:, 1], t)
                            plt.title("Retriangulation %d" % count)
                            plt.axis("equal")
                            plt.show()
                        elif dim == 3:
                            # TODO ALL 3D VIZ
                            plt.title("Retriangulation %d" % count)
                            plt.axis("equal")

            # 6. Move mesh points based on bar lengths L and forces F
            barvec = p[bars[:, 0]] - p[bars[:, 1]]  # List of bar vectors
            L = np.sqrt((barvec ** 2).sum(1))  # L = Bar lengths
            hbars = fh(p[bars].sum(1) / 2)
            L0 = (
                hbars
                * L0mult
                * ((L ** dim).sum() / (hbars ** dim).sum()) ** (1.0 / dim)
            )
            F = L0 - L
            F[F < 0] = 0  # Bar forces (scalars)
            Fvec = (
                F[:, None] / L[:, None].dot(np.ones((1, dim))) * barvec
            )  # Bar forces (x,y components)
            Ftot = mutils.dense(
                bars[:, [0] * dim + [1] * dim],
                np.repeat([list(range(dim)) * 2], len(F), axis=0),
                np.hstack((Fvec, -Fvec)),
                shape=(N, dim),
            )
            Ftot[:nfix] = 0  # Force = 0 at fixed points
            p += deltat * Ftot  # Update node positions

            # 7. Bring outside points back to the boundary
            d = fd(p)
            ix = d > 0  # Find points outside (d>0)
            if ix.any():

                def deps_vec(i):
                    a = [0] * dim
                    a[i] = deps
                    return a

                dgrads = [(fd(p[ix] + deps_vec(i)) - d[ix]) / deps for i in range(dim)]
                dgrad2 = sum(dgrad ** 2 for dgrad in dgrads)
                dgrad2 = np.where(dgrad2 < deps, deps, dgrad2)
                p[ix] -= (d[ix] * np.vstack(dgrads) / dgrad2).T  # Project

            # 8a. Termination criterion: All interior nodes move less than dptol (scaled)
            maxdp = deltat * np.sqrt((Ftot[d < -geps] ** 2).sum(1)).max()
            if count % nscreen == 0:
                print(
                    "Iteration #%d, max movement is %f, there are %d vertices and %d cells"
                    % (count + 1, maxdp, len(p), len(t)),
                    flush=True,
                )
            if maxdp < ptol * h0:
                print(
                    "Termination reached...all interior nodes move less than dptol.",
                    flush=True,
                )
                break
            # 8b. Number of iterations reached.
            if count == max_iter - 1:
                print(
                    "Termination reached...maximum number of iterations reached.",
                    flush=True,
                )
                break
            count += 1
            end = time.time()
            print("     Elapsed wall-clock time %f : " % (end - start), flush=True)
        return p, t