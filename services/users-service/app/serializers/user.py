from app.models import AgentSetting, User, UserRequest
from app.schemas.agent import AgentSettingResponse
from app.schemas.request import UserRequestResponse
from app.schemas.user import UserResponse


def user_to_response(user: User) -> UserResponse:
    return UserResponse.model_validate(user, from_attributes=True)


def agent_setting_to_response(setting: AgentSetting) -> AgentSettingResponse:
    return AgentSettingResponse.model_validate(setting, from_attributes=True)


def user_request_to_response(request: UserRequest) -> UserRequestResponse:
    return UserRequestResponse.model_validate(request, from_attributes=True)
