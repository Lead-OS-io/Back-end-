import enum


class MediaType(str, enum.Enum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"
    OTHER = "other"


class MediaPurpose(str, enum.Enum):
    PRODUCT_IMAGE = "product_image"
    CATEGORY_IMAGE = "category_image"
    PROFILE_PHOTO = "profile_photo"
    PAYMENT_RECEIPT = "payment_receipt"
    BANNER_VIDEO = "banner_video"
    OTHER = "other"
