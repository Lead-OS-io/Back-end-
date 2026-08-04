from app.models import User, UserRequest
from app.schemas.request import UserRequestResponse
from app.schemas.user import UserResponse


def user_to_response(user: User) -> UserResponse:
    return UserResponse.model_validate(user, from_attributes=True)


def user_request_to_response(request: UserRequest) -> UserRequestResponse:
    return UserRequestResponse.model_validate(request, from_attributes=True)
