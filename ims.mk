# SPDX-License-Identifier: Apache-2.0
SPRD_IMS_PATH := vendor/sprd/ims

PRODUCT_SOONG_NAMESPACES += $(SPRD_IMS_PATH)
SYSTEM_EXT_PRIVATE_SEPOLICY_DIRS += $(SPRD_IMS_PATH)/sepolicy/private
PRODUCT_PACKAGES += \
    ims_bridged \
    SprdImsService \
    SprdImsConfig \
    SprdImsDeviceConfigOverlay \
    SprdImsTelephonyOverlay

PRODUCT_COPY_FILES += \
    $(SPRD_IMS_PATH)/configs/permissions/privapp-permissions-sprd-ims-config.xml:$(TARGET_COPY_OUT_SYSTEM_EXT)/etc/permissions/privapp-permissions-sprd-ims-config.xml \
    $(SPRD_IMS_PATH)/configs/permissions/privapp-permissions-sprd-ims.xml:$(TARGET_COPY_OUT_SYSTEM_EXT)/etc/permissions/privapp-permissions-sprd-ims.xml \
    $(SPRD_IMS_PATH)/configs/permissions/sprd-radio-sdk-libraries.xml:$(TARGET_COPY_OUT_SYSTEM_EXT)/etc/permissions/sprd-radio-sdk-libraries.xml \
    $(SPRD_IMS_PATH)/proprietary/system_ext/framework/radio_interactor_common.jar:$(TARGET_COPY_OUT_SYSTEM_EXT)/framework/radio_interactor_common.jar \
    $(SPRD_IMS_PATH)/proprietary/system_ext/framework/unisoc-framework.jar:$(TARGET_COPY_OUT_SYSTEM_EXT)/framework/unisoc-framework.jar \
    $(SPRD_IMS_PATH)/proprietary/system_ext/framework/com.unisoc.sdk.common.jar:$(TARGET_COPY_OUT_SYSTEM_EXT)/framework/com.unisoc.sdk.common.jar

# Video, Wi-Fi calling and APN settings remain carrier/device-provided.
