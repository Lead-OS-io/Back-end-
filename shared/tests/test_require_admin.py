import pytest

from shared.auth.dependencies import Identity, require_admin
from shared.utils.exceptions import ForbiddenError


def test_superuser_passes():
    assert require_admin(Identity(1, 1, None, True)).is_superuser


def test_role_id_1_passes():
    assert require_admin(Identity(2, 1, 1, False)).role_id == 1


def test_regular_user_rejected():
    with pytest.raises(ForbiddenError):
        require_admin(Identity(3, 1, 2, False))
