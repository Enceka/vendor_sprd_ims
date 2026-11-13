# SPDX-License-Identifier: Apache-2.0
SPRD_IMS_PATH := vendor/sprd/ims

PRODUCT_SOONG_NAMESPACES += $(SPRD_IMS_PATH)
PRODUCT_PACKAGES += \
    SprdImsService \
    SprdImsTelephonyOverlay

# Enable the device capability and the tested 46015 carrier configuration.
# Other carriers continue to use their own CarrierConfig availability values.
ifeq ($(SPRD_IMS_ENABLE_BROADNET_VOLTE),true)
PRODUCT_PACKAGES += \
    SprdImsDeviceConfigOverlay \
    SprdImsCarrierConfigOverlay
endif

PRODUCT_COPY_FILES += \
    $(SPRD_IMS_PATH)/configs/permissions/privapp-permissions-sprd-ims.xml:$(TARGET_COPY_OUT_SYSTEM_EXT)/etc/permissions/privapp-permissions-sprd-ims.xml \
    $(SPRD_IMS_PATH)/configs/permissions/sprd-radio-sdk-libraries.xml:$(TARGET_COPY_OUT_SYSTEM_EXT)/etc/permissions/sprd-radio-sdk-libraries.xml \
    $(SPRD_IMS_PATH)/proprietary/system_ext/framework/radio_interactor_common.jar:$(TARGET_COPY_OUT_SYSTEM_EXT)/framework/radio_interactor_common.jar \
    $(SPRD_IMS_PATH)/proprietary/system_ext/framework/unisoc-framework.jar:$(TARGET_COPY_OUT_SYSTEM_EXT)/framework/unisoc-framework.jar \
    $(SPRD_IMS_PATH)/proprietary/system_ext/framework/com.unisoc.sdk.common.jar:$(TARGET_COPY_OUT_SYSTEM_EXT)/framework/com.unisoc.sdk.common.jar

# Native IMS services and the modem interfaces remain device-provided blobs.
# Video, Wi-Fi calling, VoNR and APN settings remain carrier/device-provided.
