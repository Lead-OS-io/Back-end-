from app.models import User
from app.schemas.user import UserResponse


def user_to_response(user: User) -> UserResponse:
    return UserResponse.model_validate(user, from_attributes=True)
