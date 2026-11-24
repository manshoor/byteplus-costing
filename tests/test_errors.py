import pytest

from seedance_client import errors


@pytest.mark.parametrize(
    ("status", "code", "expected"),
    [
        (401, "AuthenticationError", errors.AuthError),
        (401, "InvalidAccountStatus", errors.AccountError),
        (403, "AccountOverdueError", errors.AccountError),
        (403, "OperationDenied.ServiceOverdue", errors.AccountError),
        (403, "OperationDenied.ServiceNotOpen", errors.ModelAccessError),
        (403, "AccessDenied", errors.ModelAccessError),
        (404, "ModelNotOpen", errors.ModelAccessError),
        (404, "InvalidEndpointOrModel.NotFound", errors.ModelAccessError),
        (404, "InvalidEndpointOrModel.ModelIDAccessDisabled", errors.ModelAccessError),
        (400, "InvalidParameter", errors.InvalidInputError),
        (400, "InvalidParameter.Any", errors.InvalidInputError),
        (400, "MissingParameter.model", errors.InvalidInputError),
        (400, "InvalidImageURL.Any", errors.InvalidInputError),
        (400, "InputTextSensitiveContentDetected", errors.ContentRejectedError),
        (400, "SensitiveContentDetected.PolicyViolation", errors.ContentRejectedError),
        (429, "RateLimitExceeded.Any", errors.RateLimitError),
        (429, "ModelAccountRpmRateLimitExceeded", errors.RateLimitError),
        (429, "ModelAccountTpmRateLimitExceeded", errors.RateLimitError),
        (429, "APIAccountRpmRateLimitExceeded", errors.RateLimitError),
        (429, "AccountRateLimitExceeded", errors.RateLimitError),
        (429, "ServerOverloaded", errors.RateLimitError),
        (429, "RequestBurstTooFast", errors.RateLimitError),
        (429, "QuotaExceeded", errors.QuotaError),
        (429, "SetLimitExceeded", errors.QuotaError),
        (429, "InflightBatchsizeExceeded", errors.QuotaError),
        (500, "InternalServiceError", errors.ServerError),
        # Fallback by HTTP status when the code is new or missing.
        (400, "New", errors.InvalidInputError),
        (401, None, errors.AuthError),
        (403, "New", errors.ModelAccessError),
        (429, None, errors.RateLimitError),
        (503, None, errors.ServerError),
        (404, "NotFound.Any", errors.ApiError),
        (418, None, errors.ApiError),
    ],
)
def test_code_maps_to_class(status, code, expected):
    assert errors.classify_error(status, code) is expected


def test_exit_codes_are_unique():
    classes = [
        item
        for item in vars(errors).values()
        if isinstance(item, type) and issubclass(item, errors.SeedanceError)
    ]
    own = [item.exit_code for item in classes if "exit_code" in vars(item)]
    assert len(own) == len(set(own))
    assert 2 not in own


def test_retryable_classes():
    retryable = {errors.RateLimitError, errors.ServerError, errors.NetworkError}
    for item in vars(errors).values():
        if isinstance(item, type) and issubclass(item, errors.SeedanceError):
            assert item.retryable == (item in retryable)
