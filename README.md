# SPRD IMS

Stock UNISOC IMS integration for Android 13 / LineageOS 20, initially for RongYue E5.
It packages the IMS APK and private Java/JNI dependencies, `ims_bridged`,
RadioInteractor, device overlays and SELinux policy.

## Integration

Include after the device vendor makefile, removing its duplicate IMS package:

```make
$(call inherit-product, vendor/sprd/ims/ims.mk)
```

The device must also include `device/sprd/sepolicy_vndr`. The integration uses
existing Android services and overlays; public framework sources and the
bootclasspath remain unchanged.

`SprdImsConfig` delegates CarrierConfig requests to the platform service and
applies the stock modem's per-slot VoLTE authorization for loaded subscriptions.
VoNR uses a device default when the carrier supplies none. There is no operator
allowlist; provisioning and user preferences remain framework-controlled.

RadioInteractor runs in a separate phone-UID process. `ims_bridged` uses the
stock native socket and kernel interfaces with its own SELinux domain.

## Import and build

Use a deodexed stock dump containing `system/`, `system_ext/` and `vendor/`:

```sh
python3 vendor/sprd/ims/tools/import_stock.py /path/to/stock-dump
python3 vendor/sprd/ims/tools/import_bridge.py /path/to/stock-dump
python3 vendor/sprd/ims/tools/import_radio_interactor.py /path/to/stock-dump
```

Each importer's `--help` lists tool overrides and optional platform JAR collision
checks. Import metadata records the source hashes. After selecting the product:

```sh
m SprdImsService SprdImsConfig SprdImsDeviceConfigOverlay \
    SprdImsTelephonyOverlay SprdRadioInteractorService ims_bridged \
    selinux_policy sepolicy_tests treble_sepolicy_tests
```

Install the apps, overlays, permissions and policy together, then reboot.
IMS registration has been tested on E5; call audio distortion remains under
investigation. VoNR calls, VoWiFi, video calls and SIM switching need device testing.

Integration scripts and configuration are Apache-2.0. Imported proprietary
components retain their original rights.
