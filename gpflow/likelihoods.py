# Copyright 2016 Valentine Svensson, James Hensman, alexggmatthews, Alexis Boukouvalas
# Copyright 2017 Artem Artemev @awav
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
r"""
Likelihoods are another core component of GPflow. This describes how likely the
data is under the assumptions made about the underlying latent functions
p(Y|F). Different likelihoods make different
assumptions about the distribution of the data, as such different data-types
(continuous, binary, ordinal, count) are better modelled with different
likelihood assumptions.

Use of any likelihood other than Gaussian typically introduces the need to use
an approximation to perform inference, if one isn't already needed. A
variational inference and MCMC models are included in GPflow and allow
approximate inference with non-Gaussian likelihoods. An introduction to these
models can be found :ref:`here <implemented_models>`. Specific notebooks
illustrating non-Gaussian likelihood regressions are available for
`classification <notebooks/classification.html>`_ (binary data), `ordinal
<notebooks/ordinal.html>`_ and `multiclass <notebooks/multiclass.html>`_.

Creating new likelihoods
------------------------
Likelihoods are defined by their
log-likelihood. When creating new likelihoods, the
:func:`logp <gpflow.likelihoods.Likelihood.logp>` method (log p(Y|F)), the
:func:`conditional_mean <gpflow.likelihoods.Likelihood.conditional_mean>`,
:func:`conditional_variance
<gpflow.likelihoods.Likelihood.conditional_variance>`.

In order to perform variational inference with non-Gaussian likelihoods a term
called ``variational expectations``, ∫ q(F) log p(Y|F) dF, needs to
be computed under a Gaussian distribution q(F) ~ N(μ, Σ).

The :func:`variational_expectations <gpflow.likelihoods.Likelihood.variational_expectations>`
method can be overriden if this can be computed in closed form, otherwise; if
the new likelihood inherits
:class:`Likelihood <gpflow.likelihoods.Likelihood>` the default will use
Gauss-Hermite numerical integration (works well when F is 1D
or 2D), if the new likelihood inherits from
:class:`MonteCarloLikelihood <gpflow.likelihoods.MonteCarloLikelihood>` the
integration is done by sampling (can be more suitable when F is higher dimensional).
"""

import numpy as np
import tensorflow as tf
import abc

from . import logdensities
from . import priors
from . import settings
from . import transforms
from .decors import params_as_tensors
from .decors import params_as_tensors_for
from .params import ParamList
from .params import Parameter
from .params import Parameterized
from .quadrature import hermgauss
from .quadrature import ndiagquad, ndiag_mc


class Likelihood(Parameterized):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.num_gauss_hermite_points = 20

    def predict_mean_and_var(self, Fmu, Fvar):
        r"""
        Given a Normal distribution for the latent function,
        return the mean of Y

        i.e. if
            q(f) = N(Fmu, Fvar)

        and this object represents

            p(y|f)

        then this method computes the predictive mean

           ∫∫ y p(y|f)q(f) df dy

        and the predictive variance

           ∫∫ y^2 p(y|f)q(f) df dy  - [ ∫∫ y p(y|f)q(f) df dy ]^2

        Here, we implement a default Gauss-Hermite quadrature routine, but some
        likelihoods (e.g. Gaussian) will implement specific cases.

        :param Fmu: mean of Gaussian, q(f), to take the expectation over [N, P]
        :param Fvar: variances (independent per data) of Gaussian, q(f), to take the expectation over [N, P]
        """
        integrand2 = lambda *X: self.conditional_variance(*X) + tf.square(self.conditional_mean(*X))
        E_y, E_y2 = ndiagquad([self.conditional_mean, integrand2],
                              self.num_gauss_hermite_points,
                              Fmu, Fvar)
        V_y = E_y2 - tf.square(E_y)
        return E_y, V_y

    def predict_density(self, Fmu, Fvar, Y):
        r"""
        Given a Normal distribution for the latent function, and a datum Y,
        compute the log predictive density of Y.
        i.e. if
            q(f) = N(Fmu, Fvar)

        and this object represents

            p(y|f)

        then this method computes the predictive density

            log ∫ p(y=Y|f)q(f) df

        Here, we implement a default Gauss-Hermite quadrature routine, but some
        likelihoods (Gaussian, Poisson) will implement specific cases.

        :param Fmu: mean of Gaussian, q(f), to take the expectation over [N, P]
        :param Fvar: variances (independent per data) of Gaussian, q(f), to take the expectation over [N, P]
        """
        return ndiagquad(self.logp,
                         self.num_gauss_hermite_points,
                         Fmu, Fvar, logspace=True, Y=Y)

    def variational_expectations(self, Fmu, Fvar, Y):
        r"""
        Compute the expected log density of the data, given a Gaussian
        distribution for the function values.
        i.e. if
            q(f) = N(Fmu, Fvar)

        and this object represents

            p(y|f)

        then this method computes

           ∫ (log p(y|f)) q(f) df.

        Here, we implement a default Gauss-Hermite quadrature routine, but some
        likelihoods (Gaussian, Poisson) will implement specific cases.

        :param Fmu: mean of Gaussian, q(f), to take the expectation over [N, P]
        :param Fvar: variances (independent per data) of Gaussian, q(f), to take the expectation over [N, P]
        :param Y: observed data to use for likelihood, log p(y|f)
        """
        return ndiagquad(self.logp,
                         self.num_gauss_hermite_points,
                         Fmu, Fvar, Y=Y)

    @abc.abstractmethod
    def logp(self, F, Y):
        """
        Log probability of Y given F, where F is typically the latent function
        for each output, and Y is the data

        log p(Y|F)

        :param F: Latent function(s) [N, P]
        :param Y: Observed data [N, P]
        """
        pass

    @abc.abstractmethod
    def conditional_mean(self, F):  # pylint: disable=R0201
        """
        Conditional mean of the distribution

        E[Y|F] = ∫ Y p(Y|F) dY

        :param F: Latent function(s) [N, P]
        """
        pass

    @abc.abstractmethod
    def conditional_variance(self, F):  # pylint: disable=R0201
        """
        Conditional variance of the distribution

        Var[Y|F] = ∫ (Y-μ)² p(Y|F) dY

        where μ = E[Y|F] is the conditional_mean

        :param F: Latent function(s) [N, P]
        """
        pass


class Gaussian(Likelihood):
    r"""
    Univariate Gaussian likelihood as defined by its variance. The mean is assumed
    to be input dependant.

    p(Y|F) = 𝒩 (Y|F,Iσ²) = \prod^{N}_{i=1} 1/(2πσ²) exp[-(fᵢ - yᵢ)² / 2σ²]
    """
    def __init__(self, variance=1.0, **kwargs):
        """
        :param float variance: variance of the independent univariate Gaussian
                               likelihoods (variance > 0)
        """
        super().__init__(**kwargs)
        self.variance = Parameter(
            variance, transform=transforms.positive, dtype=settings.float_type)

    @params_as_tensors
    def logp(self, F, Y):
        return logdensities.gaussian(Y, F, self.variance)

    @params_as_tensors
    def conditional_mean(self, F):  # pylint: disable=R0201
        return tf.identity(F)

    @params_as_tensors
    def conditional_variance(self, F):
        return tf.fill(tf.shape(F), tf.squeeze(self.variance))

    @params_as_tensors
    def predict_mean_and_var(self, Fmu, Fvar):
        return tf.identity(Fmu), Fvar + self.variance

    @params_as_tensors
    def predict_density(self, Fmu, Fvar, Y):
        return logdensities.gaussian(Y, Fmu, Fvar + self.variance)

    @params_as_tensors
    def variational_expectations(self, Fmu, Fvar, Y):
        return -0.5 * np.log(2 * np.pi) - 0.5 * tf.log(self.variance) \
               - 0.5 * (tf.square(Y - Fmu) + Fvar) / self.variance


class Poisson(Likelihood):
    """
    Poisson likelihood for use with count data, where the rate is given by the
    (transformed) GP.

    Let g(.) be the inverse-link function, then this likelihood represents

    p(yᵢ | fᵢ) = Poisson(yᵢ | g(fᵢ) * bᵢ) = [g(fᵢ)*bᵢ]^{yᵢ} exp(-g(fᵢ)*bᵢ) / yᵢ!

    where bᵢ is the binsize for each datapoint. If a scalar is provided for
    binsize, it is assumed that each datapoint has the same binsize.

    Note: binsize
    For use in a Log Gaussian Cox process (doubly stochastic model) where the
    rate function of an inhomogeneous Poisson process is given by a GP.  The
    intractable likelihood can be approximated by gridding the space (into bins
    of size 'binsize') and using this Poisson likelihood.
    """

    def __init__(self, invlink=tf.exp, binsize=1., **kwargs):
        """
        :param invlink: inverse link function, often used to transform the
                        latent function to ensure that the rate of the Poisson
                        is positive
        :type invlink: :class:`gpflow.transforms.Transform`
        :param float binsize: binsize in which latent function is assumed to
                             constant (as an approximation)
        """
        super().__init__(**kwargs)
        self.invlink = invlink
        self.binsize = np.double(binsize)

    def logp(self, F, Y):
        return logdensities.poisson(Y, self.invlink(F) * self.binsize)

    def conditional_variance(self, F):
        return self.invlink(F) * self.binsize

    def conditional_mean(self, F):
        return self.invlink(F) * self.binsize

    def variational_expectations(self, Fmu, Fvar, Y):
        if self.invlink is tf.exp:
            return Y * Fmu - tf.exp(Fmu + Fvar / 2) * self.binsize \
                   - tf.lgamma(Y + 1) + Y * tf.log(self.binsize)
        return super(Poisson, self).variational_expectations(Fmu, Fvar, Y)


class Exponential(Likelihood):
    """
    Exponential likelihood for positive continuous data, where the rate is
    given by the (transformed) GP.

    Let g(.) be the inverse-link function, then this likelihood represents

    p(yᵢ|fᵢ) = g(fᵢ)exp(-g(fᵢ)yᵢ)
    """
    def __init__(self, invlink=tf.exp, **kwargs):
        """
        :param invlink: inverse link function, often used to transform the
                        latent function to ensure that the rate of the
                        Exponential is positive
        :type invlink: :class:`gpflow.transforms.Transform`
        """
        super().__init__(**kwargs)
        self.invlink = invlink

    def logp(self, F, Y):
        return logdensities.exponential(Y, self.invlink(F))

    def conditional_mean(self, F):
        return self.invlink(F)

    def conditional_variance(self, F):
        return tf.square(self.invlink(F))

    def variational_expectations(self, Fmu, Fvar, Y):
        if self.invlink is tf.exp:
            return - tf.exp(-Fmu + Fvar / 2) * Y - Fmu
        return super().variational_expectations(Fmu, Fvar, Y)


class StudentT(Likelihood):
    """
    Student-T likelihood for continuous heavy tailed data.

    p(yᵢ|fᵢ) = [ Γ((v+1)/2) / Γ(v/2)√(vπ)σ ]
               × [1 + (1/v)((yᵢ - fᵢ)/2)²]^{-(v+1)/2}

    where v is the degrees of freedom (df).

    Note: df
    for the conditional variance is only defined for df > 2
    """

    def __init__(self, scale=1.0, df=3.0, **kwargs):
        """
        :param scale float: scale parameter
        :param df float: degrees of freedom
        """
        super().__init__(**kwargs)
        self.df = df
        self.scale = Parameter(scale, transform=transforms.positive,
                               dtype=settings.float_type)

    @params_as_tensors
    def logp(self, F, Y):
        return logdensities.student_t(Y, F, self.scale, self.df)

    @params_as_tensors
    def conditional_mean(self, F):
        return tf.identity(F)

    @params_as_tensors
    def conditional_variance(self, F):
        var = self.scale ** 2 * (self.df / (self.df - 2.0))
        return tf.fill(tf.shape(F), tf.squeeze(var))


def inv_probit(x):
    jitter = 1e-3  # ensures output is strictly between 0 and 1
    return 0.5 * (1.0 + tf.erf(x / np.sqrt(2.0))) * (1 - 2 * jitter) + jitter


class Bernoulli(Likelihood):
    """
    Bernoulli likelihood for binary data, classification where the probability
    of the class being equal to 1 is given by the (transformed) GP.

    Let g(.) be the inverse-link function, then this likelihood represents

    p(yᵢ|fᵢ) = g(fᵢ)ᵏ(1-g(fᵢ))¹⁻ᵏ
    """
    def __init__(self, invlink=inv_probit, **kwargs):
        """
        :param invlink: inverse link function, used to transform the latent
                        function to ensure that the function is between 0 and 1
        :type invlink: :class:`gpflow.transforms.Transform`
        """
        super().__init__(**kwargs)
        self.invlink = invlink

    def logp(self, F, Y):
        return logdensities.bernoulli(Y, self.invlink(F))

    def predict_mean_and_var(self, Fmu, Fvar):
        if self.invlink is inv_probit:
            p = inv_probit(Fmu / tf.sqrt(1 + Fvar))
            return p, p - tf.square(p)
        else:
            # for other invlink, use quadrature
            return super().predict_mean_and_var(Fmu, Fvar)

    def predict_density(self, Fmu, Fvar, Y):
        p = self.predict_mean_and_var(Fmu, Fvar)[0]
        return logdensities.bernoulli(Y, p)

    def conditional_mean(self, F):
        return self.invlink(F)

    def conditional_variance(self, F):
        p = self.conditional_mean(F)
        return p - tf.square(p)


class Gamma(Likelihood):
    """
    Gamma likelihood for positive data, where the *scale* (θ, inverse rate)
    of the Gamma distribution is given by the (transformed) GP.

    Let g(.) be the inverse-link function, then this likelihood represents

    p(yᵢ|fᵢ) = {1 / Γ(k)g(fᵢ)ᵏ}yᵢᵏ⁻¹exp(-yᵢ/g(fᵢ))

    The shape, k, is not input dependant.
    """

    def __init__(self, invlink=tf.exp, **kwargs):
        """
        :param invlink: inverse link function, used to transform the latent
                        function to ensure that the scale is positive
        :type invlink: :class:`gpflow.transforms.Transform`
        """
        super().__init__(**kwargs)
        self.invlink = invlink
        self.shape = Parameter(1.0, transform=transforms.positive)

    @params_as_tensors
    def logp(self, F, Y):
        return logdensities.gamma(Y, self.shape, self.invlink(F))

    @params_as_tensors
    def conditional_mean(self, F):
        return self.shape * self.invlink(F)

    @params_as_tensors
    def conditional_variance(self, F):
        scale = self.invlink(F)
        return self.shape * tf.square(scale)

    @params_as_tensors
    def variational_expectations(self, Fmu, Fvar, Y):
        if self.invlink is tf.exp:
            return -self.shape * Fmu - tf.lgamma(self.shape) \
                   + (self.shape - 1.) * tf.log(Y) - Y * tf.exp(-Fmu + Fvar / 2.)
        else:
            return super().variational_expectations(Fmu, Fvar, Y)


class Beta(Likelihood):
    """
    Beta likelihood for data between 0 and 1.

    This uses a reparameterisation of the Beta density such that the *mean*, μ,
    of the Beta distribution is given by the (transformed) GP, which restricts
    the mean of the distribution to be between 0 and 1.

    Let g(.) be the inverse-link function, the mean is thus given by μᵢ = g(fᵢ)

    in addition the distribution has a scale parameter. The scale parameter is
    not input dependant.
    The familiar alpha, beta parameters are given by

    μ     = α / (α + β)

    scale = α + β

    as such the input dependant shape parameters of the Beta distribution are
    given by

    αᵢ = scale * g(fᵢ)

    βᵢ = scale * (1-g(fᵢ))

    Finally the likelihood is parameterised as:

    p(yᵢ|fᵢ) = yᵢ^{αᵢ-1}(1-yᵢ)^{βᵢ-1) / B(αᵢ,βᵢ)

    where B(αᵢ,βᵢ) is the Beta function:

    B(αᵢ,βᵢ) = Γ(αᵢ)Γ(βᵢ) / Γ(αᵢ + βᵢ)

    """

    def __init__(self, invlink=inv_probit, scale=1.0, **kwargs):
        """
        :param invlink: inverse link function, used to transform the latent
                        function to ensure that the mean is between 0 and 1
        :type invlink: :class:`gpflow.transforms.Transform`
        """
        super().__init__(**kwargs)
        self.scale = Parameter(scale, transform=transforms.positive)
        self.invlink = invlink

    @params_as_tensors
    def logp(self, F, Y):
        mean = self.invlink(F)
        alpha = mean * self.scale
        beta = self.scale - alpha
        return logdensities.beta(Y, alpha, beta)

    @params_as_tensors
    def conditional_mean(self, F):
        return self.invlink(F)

    @params_as_tensors
    def conditional_variance(self, F):
        mean = self.invlink(F)
        return (mean - tf.square(mean)) / (self.scale + 1.)


class RobustMax(Parameterized):
    """
    This class represent a multi-class inverse-link function. Given a vector
    f=[f_1, f_2, ... f_k], the result of the mapping is

    y = [y_1 ... y_k]

    with

    y_i = (1-eps)  i == argmax(f)
          eps/(k-1)  otherwise.
    """

    def __init__(self, num_classes, epsilon=1e-3, **kwargs):
        super().__init__(**kwargs)
        self.epsilon = Parameter(epsilon, transforms.Logistic(), trainable=False, dtype=settings.float_type,
                                 prior=priors.Beta(0.2, 5.))
        self.num_classes = num_classes

    @params_as_tensors
    def __call__(self, F):
        i = tf.argmax(F, 1)
        return tf.one_hot(i, self.num_classes, tf.squeeze(1. - self.epsilon), tf.squeeze(self._eps_K1))

    @property
    @params_as_tensors
    def _eps_K1(self):
        return self.epsilon / (self.num_classes - 1.)

    def prob_is_largest(self, Y, mu, var, gh_x, gh_w):
        Y = tf.cast(Y, tf.int64)
        # work out what the mean and variance is of the indicated latent function.
        oh_on = tf.cast(tf.one_hot(tf.reshape(Y, (-1,)), self.num_classes, 1., 0.), settings.float_type)
        mu_selected = tf.reduce_sum(oh_on * mu, 1)
        var_selected = tf.reduce_sum(oh_on * var, 1)

        # generate Gauss Hermite grid
        X = tf.reshape(mu_selected, (-1, 1)) + gh_x * tf.reshape(
            tf.sqrt(tf.clip_by_value(2. * var_selected, 1e-10, np.inf)), (-1, 1))

        # compute the CDF of the Gaussian between the latent functions and the grid (including the selected function)
        dist = (tf.expand_dims(X, 1) - tf.expand_dims(mu, 2)) / tf.expand_dims(
            tf.sqrt(tf.clip_by_value(var, 1e-10, np.inf)), 2)
        cdfs = 0.5 * (1.0 + tf.erf(dist / np.sqrt(2.0)))

        cdfs = cdfs * (1 - 2e-4) + 1e-4

        # blank out all the distances on the selected latent function
        oh_off = tf.cast(tf.one_hot(tf.reshape(Y, (-1,)), self.num_classes, 0., 1.), settings.float_type)
        cdfs = cdfs * tf.expand_dims(oh_off, 2) + tf.expand_dims(oh_on, 2)

        # take the product over the latent functions, and the sum over the GH grid.
        return tf.matmul(tf.reduce_prod(cdfs, reduction_indices=[1]), tf.reshape(gh_w / np.sqrt(np.pi), (-1, 1)))


class MultiClass(Likelihood):
    def __init__(self, num_classes, invlink=None, **kwargs):
        """
        A likelihood that can do multi-way classification.
        Currently the only valid choice
        of inverse-link function (invlink) is an instance of RobustMax.
        """
        super().__init__(**kwargs)
        self.num_classes = num_classes
        if invlink is None:
            invlink = RobustMax(self.num_classes)
        elif not isinstance(invlink, RobustMax):
            raise NotImplementedError
        self.invlink = invlink

    def logp(self, F, Y):
        if isinstance(self.invlink, RobustMax):
            with params_as_tensors_for(self.invlink):
                hits = tf.equal(tf.expand_dims(tf.argmax(F, 1), 1), tf.cast(Y, tf.int64))
                yes = tf.ones(tf.shape(Y), dtype=settings.float_type) - self.invlink.epsilon
                no = tf.zeros(tf.shape(Y), dtype=settings.float_type) + self.invlink._eps_K1
                p = tf.where(hits, yes, no)
            return tf.log(p)
        else:
            raise NotImplementedError

    def variational_expectations(self, Fmu, Fvar, Y):
        if isinstance(self.invlink, RobustMax):
            with params_as_tensors_for(self.invlink):
                gh_x, gh_w = hermgauss(self.num_gauss_hermite_points)
                p = self.invlink.prob_is_largest(Y, Fmu, Fvar, gh_x, gh_w)
                ve = p * tf.log(1. - self.invlink.epsilon) + (1. - p) * tf.log(self.invlink._eps_K1)
            return ve
        else:
            raise NotImplementedError

    def predict_mean_and_var(self, Fmu, Fvar):
        if isinstance(self.invlink, RobustMax):
            # To compute this, we'll compute the density for each possible output
            possible_outputs = [tf.fill(tf.stack([tf.shape(Fmu)[0], 1]), np.array(i, dtype=np.int64)) for i in
                                range(self.num_classes)]
            ps = [self._predict_non_logged_density(Fmu, Fvar, po) for po in possible_outputs]
            ps = tf.transpose(tf.stack([tf.reshape(p, (-1,)) for p in ps]))
            return ps, ps - tf.square(ps)
        else:
            raise NotImplementedError

    def predict_density(self, Fmu, Fvar, Y):
        return tf.log(self._predict_non_logged_density(Fmu, Fvar, Y))

    def _predict_non_logged_density(self, Fmu, Fvar, Y):
        if isinstance(self.invlink, RobustMax):
            with params_as_tensors_for(self.invlink):
                gh_x, gh_w = hermgauss(self.num_gauss_hermite_points)
                p = self.invlink.prob_is_largest(Y, Fmu, Fvar, gh_x, gh_w)
                den = p * (1. - self.invlink.epsilon) + (1. - p) * (self.invlink._eps_K1)
            return den
        else:
            raise NotImplementedError

    def conditional_mean(self, F):
        return self.invlink(F)

    def conditional_variance(self, F):
        p = self.conditional_mean(F)
        return p - tf.square(p)


class SwitchedLikelihood(Likelihood):
    def __init__(self, likelihood_list, **kwargs):
        """
        In this likelihood, we assume at extra column of Y, which contains
        integers that specify a likelihood from the list of likelihoods.
        """
        super().__init__(**kwargs)
        for l in likelihood_list:
            assert isinstance(l, Likelihood)
        self.likelihood_list = ParamList(likelihood_list)
        self.num_likelihoods = len(self.likelihood_list)

    def _partition_and_stitch(self, args, func_name):
        """
        args is a list of tensors, to be passed to self.likelihoods.<func_name>

        args[-1] is the 'Y' argument, which contains the indexes to self.likelihoods.

        This function splits up the args using dynamic_partition, calls the
        relevant function on the likelihoods, and re-combines the result.
        """
        # get the index from Y
        Y = args[-1]
        ind = Y[:, -1]
        ind = tf.cast(ind, tf.int32)
        Y = Y[:, :-1]
        args[-1] = Y

        # split up the arguments into chunks corresponding to the relevant likelihoods
        args = zip(*[tf.dynamic_partition(X, ind, self.num_likelihoods) for X in args])

        # apply the likelihood-function to each section of the data
        with params_as_tensors_for(self, convert=False):
            funcs = [getattr(lik, func_name) for lik in self.likelihood_list]
        results = [f(*args_i) for f, args_i in zip(funcs, args)]

        # stitch the results back together
        partitions = tf.dynamic_partition(tf.range(0, tf.size(ind)), ind, self.num_likelihoods)
        results = tf.dynamic_stitch(partitions, results)

        return results

    def logp(self, F, Y):
        return self._partition_and_stitch([F, Y], 'logp')

    def predict_density(self, Fmu, Fvar, Y):
        return self._partition_and_stitch([Fmu, Fvar, Y], 'predict_density')

    def variational_expectations(self, Fmu, Fvar, Y):
        return self._partition_and_stitch([Fmu, Fvar, Y], 'variational_expectations')

    def predict_mean_and_var(self, Fmu, Fvar):
        mvs = [lik.predict_mean_and_var(Fmu, Fvar) for lik in self.likelihood_list]
        mu_list, var_list = zip(*mvs)
        mu = tf.concat(mu_list, 1)
        var = tf.concat(var_list, 1)
        return mu, var


class Ordinal(Likelihood):
    """
    A likelihood for doing ordinal regression.

    The data are integer values from 0 to K, and the user must specify (K-1)
    'bin edges' which define the points at which the labels switch. Let the bin
    edges be [a_0, a_1, ... a_{K-1}], then the likelihood is

    p(Y=0|F) = phi((a_0 - F) / sigma)
    p(Y=1|F) = phi((a_1 - F) / sigma) - phi((a_0 - F) / sigma)
    p(Y=2|F) = phi((a_2 - F) / sigma) - phi((a_1 - F) / sigma)
    ...
    p(Y=K|F) = 1 - phi((a_{K-1} - F) / sigma)

    where phi is the cumulative density function of a Gaussian (the inverse probit
    function) and sigma is a parameter to be learned. A reference is:

    @article{chu2005gaussian,
      title={Gaussian processes for ordinal regression},
      author={Chu, Wei and Ghahramani, Zoubin},
      journal={Journal of Machine Learning Research},
      volume={6},
      number={Jul},
      pages={1019--1041},
      year={2005}
    }
    """

    def __init__(self, bin_edges, **kwargs):
        """
        bin_edges is a numpy array specifying at which function value the
        output label should switch. If the possible Y values are 0...K, then
        the size of bin_edges should be (K-1).
        """
        super().__init__(**kwargs)
        self.bin_edges = bin_edges
        self.num_bins = bin_edges.size + 1
        self.sigma = Parameter(1.0, transform=transforms.positive)

    @params_as_tensors
    def logp(self, F, Y):
        Y = tf.cast(Y, tf.int64)
        scaled_bins_left = tf.concat([self.bin_edges / self.sigma, np.array([np.inf])], 0)
        scaled_bins_right = tf.concat([np.array([-np.inf]), self.bin_edges / self.sigma], 0)
        selected_bins_left = tf.gather(scaled_bins_left, Y)
        selected_bins_right = tf.gather(scaled_bins_right, Y)

        return tf.log(inv_probit(selected_bins_left - F / self.sigma) -
                      inv_probit(selected_bins_right - F / self.sigma) + 1e-6)

    @params_as_tensors
    def _make_phi(self, F):
        """
        A helper function for making predictions. Constructs a probability
        matrix where each row output the probability of the corresponding
        label, and the rows match the entries of F.

        Note that a matrix of F values is flattened.
        """
        scaled_bins_left = tf.concat([self.bin_edges / self.sigma, np.array([np.inf])], 0)
        scaled_bins_right = tf.concat([np.array([-np.inf]), self.bin_edges / self.sigma], 0)
        return inv_probit(scaled_bins_left - tf.reshape(F, (-1, 1)) / self.sigma) \
               - inv_probit(scaled_bins_right - tf.reshape(F, (-1, 1)) / self.sigma)

    def conditional_mean(self, F):
        phi = self._make_phi(F)
        Ys = tf.reshape(np.arange(self.num_bins, dtype=np.float64), (-1, 1))
        return tf.reshape(tf.matmul(phi, Ys), tf.shape(F))

    def conditional_variance(self, F):
        phi = self._make_phi(F)
        Ys = tf.reshape(np.arange(self.num_bins, dtype=np.float64), (-1, 1))
        E_y = tf.matmul(phi, Ys)
        E_y2 = tf.matmul(phi, tf.square(Ys))
        return tf.reshape(E_y2 - tf.square(E_y), tf.shape(F))


class MonteCarloLikelihood(Likelihood):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.num_monte_carlo_points = 100
        del self.num_gauss_hermite_points

    def _mc_quadrature(self, funcs, Fmu, Fvar, logspace: bool = False, epsilon=None, **Ys):
        return ndiag_mc(funcs, self.num_monte_carlo_points, Fmu, Fvar, logspace, epsilon, **Ys)

    def predict_mean_and_var(self, Fmu, Fvar, epsilon=None):
        r"""
        Given a Normal distribution for the latent function,
        return the mean of Y

        if
            q(f) = N(Fmu, Fvar)

        and this object represents

            p(y|f)

        then this method computes the predictive mean

           ∫∫ y p(y|f)q(f) df dy

        and the predictive variance

           ∫∫ y^2 p(y|f)q(f) df dy  - [ ∫∫ y p(y|f)q(f) df dy ]^2

        Here, we implement a default Monte Carlo routine.

        :param Fmu: mean of Gaussian, q(f), to take the expectation over [N, P]
        :param Fvar: variances (independent per data) of Gaussian, q(f), to take the expectation over [N, P]
        """
        integrand2 = lambda *X: self.conditional_variance(*X) + tf.square(self.conditional_mean(*X))
        E_y, E_y2 = self._mc_quadrature([self.conditional_mean, integrand2],
                                        Fmu, Fvar, epsilon=epsilon)
        V_y = E_y2 - tf.square(E_y)
        return E_y, V_y  # N x D

    def predict_density(self, Fmu, Fvar, Y, epsilon=None):
        r"""
        Given a Normal distribution for the latent function, and a datum Y,
        compute the log predictive density of Y.

        i.e. if
            q(f) = N(Fmu, Fvar)

        and this object represents

            p(y|f)

        then this method computes the predictive density

            log ∫ p(y=Y|f)q(f) df

        Here, we implement a default Monte Carlo routine.

        :param Fmu: mean of Gaussian, q(f), to take the expectation over [N, P]
        :param Fvar: variances (independent per data) of Gaussian, q(f), to take the expectation over [N, P]
        """
        return self._mc_quadrature(self.logp, Fmu, Fvar, Y=Y, logspace=True, epsilon=epsilon)

    def variational_expectations(self, Fmu, Fvar, Y, epsilon=None):
        r"""
        Compute the expected log density of the data, given a Gaussian
        distribution for the function values.

        if
            q(f) = N(Fmu, Fvar)

        and this object represents

            p(y|f)  - Y: N x 1

        then this method computes

           \int (\log p(y|f)) q(f) df.

        Here, we implement a default Monte Carlo quadrature routine.

        :param Fmu: mean of Gaussian, q(f), to take the expectation over [N, P]
        :param Fvar: variances (independent per data) of Gaussian, q(f), to take the expectation over [N, P]
        :param Y: observed data to use for likelihood, log p(y|f)
        """
        return self._mc_quadrature(self.logp, Fmu, Fvar, Y=Y, epsilon=epsilon)


class GaussianMC(MonteCarloLikelihood, Gaussian):
    """
    Stochastic version of Gaussian likelihood for comparison.
    """
    pass


class SoftMax(MonteCarloLikelihood):
    """
    The soft-max multi-class likelihood.
    """

    def __init__(self, num_classes, **kwargs):
        super().__init__(**kwargs)
        self.num_classes = num_classes

    def logp(self, F, Y):
        with tf.control_dependencies(
                [
                    tf.assert_equal(tf.shape(Y)[1], 1),
                    tf.assert_equal(tf.cast(tf.shape(F)[1], settings.int_type),
                                    tf.cast(self.num_classes, settings.int_type))
                ]):
            return -tf.nn.sparse_softmax_cross_entropy_with_logits(logits=F, labels=Y[:, 0])[:, None]

    def conditional_mean(self, F):
        return tf.nn.softmax(F)

    def conditional_variance(self, F):
        p = self.conditional_mean(F)
        return p - tf.square(p)
