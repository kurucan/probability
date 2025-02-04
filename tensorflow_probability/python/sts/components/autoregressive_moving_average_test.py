# Copyright 2021 The TensorFlow Probability Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ============================================================================
"""Autoregressive State Space Model Tests."""

# Dependency imports
import numpy as np
import tensorflow.compat.v1 as tf1
import tensorflow.compat.v2 as tf

import tensorflow_probability as tfp

from tensorflow_probability.python.internal import tensorshape_util
from tensorflow_probability.python.internal import test_util
from tensorflow_probability.python.sts import AutoregressiveMovingAverageStateSpaceModel
from tensorflow_probability.python.sts import AutoregressiveStateSpaceModel

tfd = tfp.distributions


def arma_explicit_logp(y, ar_coefs, ma_coefs, level_scale):
  """Manual log-prob computation for arma(p, q) process."""
  # Source: page 132 of
  # http://www.ru.ac.bd/stat/wp-content/uploads/sites/25/2019/03/504_02_Hamilton_Time-Series-Analysis.pdf
  p = len(ar_coefs)
  q = len(ma_coefs)
  t = len(y)

  # For the first few steps of y, where previous values
  # are not available, we model them as zero-mean with
  # stddev `prior_scale`.
  e = np.zeros([t])
  for i in range(p):
    zero_padded_y = np.zeros([p])
    zero_padded_y[p - i:p] = y[:i]
    pred_y = np.dot(zero_padded_y, ar_coefs[::-1])
    e[i] = y[i] - pred_y

  for i in range(p, len(y)):
    pred_y = (np.dot(y[i - p:i], ar_coefs[::-1]) +
              np.dot(e[i - q:i], ma_coefs[::-1]))
    e[i] = y[i] - pred_y
  lp = (-((t - p) / 2) * np.log(2 * np.pi)
        - ((t - p) / 2) * np.log(level_scale ** 2)
        - np.sum(e ** 2 / (2 * level_scale ** 2)))

  return lp


class _AutoregressiveMovingAverageStateSpaceModelTest(test_util.TestCase):

  def testEqualsAutoregressive(self):

    # An ARMA(p, 0) process is just an AR(p) processes
    num_timesteps = 10
    observed_time_series = self._build_placeholder(
        np.random.randn(num_timesteps, 1))

    level_scale = self._build_placeholder(0.1)

    # We'll test an AR1 process, and also (just for kicks) that the trivial
    # embedding as an AR2 process gives the same model.
    coefficients_order1 = np.array([1.]).astype(self.dtype)
    coefficients_order2 = np.array([1., 1.]).astype(self.dtype)

    ar1_ssm = AutoregressiveStateSpaceModel(
        num_timesteps=num_timesteps,
        coefficients=coefficients_order1,
        level_scale=level_scale,
        initial_state_prior=tfd.MultivariateNormalDiag(
            scale_diag=[level_scale]))
    ar2_ssm = AutoregressiveStateSpaceModel(
        num_timesteps=num_timesteps,
        coefficients=coefficients_order2,
        level_scale=level_scale,
        initial_state_prior=tfd.MultivariateNormalDiag(
            scale_diag=[level_scale, 1.]))
    arma1_ssm = AutoregressiveMovingAverageStateSpaceModel(
        num_timesteps=num_timesteps,
        ar_coefficients=coefficients_order1,
        ma_coefficients=np.array([0.]).astype(self.dtype),
        level_scale=level_scale,
        initial_state_prior=tfd.MultivariateNormalDiag(
            scale_diag=[level_scale, 1.]))
    arma2_ssm = AutoregressiveMovingAverageStateSpaceModel(
        num_timesteps=num_timesteps,
        ar_coefficients=coefficients_order2,
        ma_coefficients=np.array([0.]).astype(self.dtype),
        level_scale=level_scale,
        initial_state_prior=tfd.MultivariateNormalDiag(
            scale_diag=[level_scale, 1.]))

    ar1_lp, arma1_lp, ar2_lp, arma2_lp = (
        ar1_ssm.log_prob(observed_time_series),
        arma1_ssm.log_prob(observed_time_series),
        ar2_ssm.log_prob(observed_time_series),
        arma2_ssm.log_prob(observed_time_series)
    )
    self.assertAllClose(ar1_lp, arma1_lp)
    self.assertAllClose(ar2_lp, arma2_lp)

  def testLogprobCorrectness(self):
    # Compare the state-space model's log-prob to an explicit implementation.
    num_timesteps = 10
    observed_time_series_ = np.random.randn(num_timesteps)
    ar_coefficients_ = np.array([.7, -.1]).astype(self.dtype)
    ma_coefficients_ = np.array([0.5, -0.4]).astype(self.dtype)
    level_scale_ = 1.0

    observed_time_series = self._build_placeholder(observed_time_series_)
    level_scale = self._build_placeholder(level_scale_)

    expected_logp = arma_explicit_logp(
        observed_time_series_, ar_coefficients_, ma_coefficients_, level_scale_)

    ssm = AutoregressiveMovingAverageStateSpaceModel(
        num_timesteps=num_timesteps,
        ar_coefficients=ar_coefficients_,
        ma_coefficients=ma_coefficients_,
        level_scale=level_scale,
        initial_state_prior=tfd.MultivariateNormalDiag(
            scale_diag=[level_scale, 0., 0.]))

    lp = ssm.log_prob(observed_time_series[..., tf.newaxis])
    self.assertAllClose(lp, expected_logp, rtol=5e-2)

  def testBatchShape(self):
    # Check that the model builds with batches of parameters.
    order = 3
    batch_shape = [4, 2]

    # No `_build_placeholder`, because coefficients must have static shape.
    coefficients = np.random.randn(*(batch_shape + [order])).astype(self.dtype)
    order = max(order, order + 1)  # shape of initial_state_prior, scale_diag

    level_scale = self._build_placeholder(
        np.exp(np.random.randn(*batch_shape)))

    ssm = AutoregressiveMovingAverageStateSpaceModel(
        num_timesteps=10,
        ar_coefficients=coefficients,
        ma_coefficients=coefficients,
        level_scale=level_scale,
        initial_state_prior=tfd.MultivariateNormalDiag(
            scale_diag=self._build_placeholder(np.ones([order]))))
    if self.use_static_shape:
      self.assertAllEqual(tensorshape_util.as_list(ssm.batch_shape),
                          batch_shape)
    else:
      self.assertAllEqual(ssm.batch_shape_tensor(), batch_shape)

    y = ssm.sample(seed=test_util.test_seed(sampler_type='stateless'))
    if self.use_static_shape:
      self.assertAllEqual(tensorshape_util.as_list(y.shape)[:-2], batch_shape)
    else:
      self.assertAllEqual(tf.shape(y)[:-2], batch_shape)

  def _build_placeholder(self, ndarray):
    """Convert a numpy array to a TF placeholder.

    Args:
      ndarray: any object convertible to a numpy array via `np.asarray()`.

    Returns:
      placeholder: a TensorFlow `placeholder` with default value given by the
      provided `ndarray`, dtype given by `self.dtype`, and shape specified
      statically only if `self.use_static_shape` is `True`.
    """

    ndarray = np.asarray(ndarray).astype(self.dtype)
    return tf1.placeholder_with_default(
        ndarray, shape=ndarray.shape if self.use_static_shape else None)


@test_util.test_all_tf_execution_regimes
class AutoregressiveMovingAverageStateSpaceModelTestStaticShape32(
    _AutoregressiveMovingAverageStateSpaceModelTest):
  dtype = np.float32
  use_static_shape = True


@test_util.test_all_tf_execution_regimes
class AutoregressiveMovingAverageStateSpaceModelTestDynamicShape32(
    _AutoregressiveMovingAverageStateSpaceModelTest):
  dtype = np.float32
  use_static_shape = False


@test_util.test_all_tf_execution_regimes
class AutoregressiveMovingAverageStateSpaceModelTestStaticShape64(
    _AutoregressiveMovingAverageStateSpaceModelTest):
  dtype = np.float64
  use_static_shape = True

# Don't run tests for the base class.
del _AutoregressiveMovingAverageStateSpaceModelTest


if __name__ == '__main__':
  test_util.main()
