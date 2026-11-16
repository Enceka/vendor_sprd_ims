package com.sprd.ims.config;

import android.app.Application;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemProperties;
import android.service.carrier.CarrierIdentifier;
import android.telephony.CarrierConfigManager;
import android.telephony.SubscriptionInfo;
import android.telephony.SubscriptionManager;
import android.telephony.TelephonyManager;
import android.util.Log;
import android.util.SparseArray;

import java.io.PrintWriter;
import java.util.List;
import java.util.Objects;

final class ImsConfigController {
    private static final String TAG = "SprdImsConfig";
    private static final String MODEM_PROPERTY = "gsm.sys.sim.volte.allowedplmn";
    private static final String ENABLE_PROPERTY = "persist.vendor.sys.volte.enable";
    private static final long REFRESH_INTERVAL_MILLIS = 5000;

    private final Application mApplication;
    private final Handler mHandler = new Handler(Looper.getMainLooper());
    private final SubscriptionManager mSubscriptions;
    private final TelephonyManager mTelephony;
    private final CarrierConfigManager mCarrierConfig;
    private final CarrierConfigDelegate mDelegate;
    private final SparseArray<SlotState> mStates = new SparseArray<>();
    private final Runnable mRefresh = this::refresh;
    private final SubscriptionManager.OnSubscriptionsChangedListener mSubscriptionListener =
            new SubscriptionManager.OnSubscriptionsChangedListener() {
                @Override
                public void onSubscriptionsChanged() {
                    scheduleRefresh();
                }
            };
    private final BroadcastReceiver mReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            scheduleRefresh();
        }
    };
    private final BroadcastReceiver mPackageReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            if (intent.getData() != null && CarrierConfigDelegate.PACKAGE_NAME.equals(
                    intent.getData().getSchemeSpecificPart())) {
                mDelegate.rebind();
            }
        }
    };

    ImsConfigController(Application application) {
        mApplication = application;
        mSubscriptions = application.getSystemService(SubscriptionManager.class);
        mTelephony = application.getSystemService(TelephonyManager.class);
        mCarrierConfig = application.getSystemService(CarrierConfigManager.class);
        mDelegate = new CarrierConfigDelegate(application, mHandler, () -> {
            mStates.clear();
            scheduleRefresh();
        });
    }

    void start() {
        mSubscriptions.addOnSubscriptionsChangedListener(mApplication.getMainExecutor(),
                mSubscriptionListener);
        IntentFilter filter = new IntentFilter();
        filter.addAction(TelephonyManager.ACTION_SIM_APPLICATION_STATE_CHANGED);
        filter.addAction(TelephonyManager.ACTION_SIM_CARD_STATE_CHANGED);
        filter.addAction(TelephonyManager.ACTION_MULTI_SIM_CONFIG_CHANGED);
        filter.addAction(CarrierConfigManager.ACTION_CARRIER_CONFIG_CHANGED);
        mApplication.registerReceiver(mReceiver, filter, Context.RECEIVER_EXPORTED);
        IntentFilter packageFilter = new IntentFilter(Intent.ACTION_PACKAGE_REPLACED);
        packageFilter.addDataScheme("package");
        mApplication.registerReceiver(mPackageReceiver, packageFilter, Context.RECEIVER_EXPORTED);
        mDelegate.bind();
        scheduleRefresh();
    }

    CarrierConfigDelegate getDelegate() {
        return mDelegate;
    }

    SlotState getState(int phoneId) {
        SubscriptionInfo info = mSubscriptions.getActiveSubscriptionInfoForSimSlotIndex(phoneId);
        int subscriptionId = info == null ? SubscriptionManager.INVALID_SUBSCRIPTION_ID
                : info.getSubscriptionId();
        boolean loaded = info != null && mTelephony.createForSubscriptionId(subscriptionId)
                .getSimApplicationState() == TelephonyManager.SIM_STATE_LOADED;
        boolean enabled = SystemProperties.getBoolean(ENABLE_PROPERTY, false);
        boolean allowed = loaded && ImsConfigPolicy.isModemAllowed(
                SystemProperties.get(MODEM_PROPERTY), phoneId);
        return new SlotState(subscriptionId, loaded, enabled, allowed);
    }

    boolean matchesCarrier(int subscriptionId, CarrierIdentifier identifier) {
        if (identifier == null || !SubscriptionManager.isValidSubscriptionId(subscriptionId)) {
            return false;
        }
        TelephonyManager telephony = mTelephony.createForSubscriptionId(subscriptionId);
        String operator = telephony.getSimOperator();
        if (operator == null || operator.length() < 5
                || !operator.equals(identifier.getMcc() + identifier.getMnc())) {
            return false;
        }
        return identifier.getImsi() == null || identifier.getImsi().isEmpty()
                || identifier.getImsi().equals(telephony.getSubscriberId());
    }

    private void scheduleRefresh() {
        mHandler.removeCallbacks(mRefresh);
        mHandler.post(mRefresh);
    }

    private void refresh() {
        mHandler.removeCallbacks(mRefresh);
        boolean poll = false;
        try {
            List<SubscriptionInfo> active = mSubscriptions.getCompleteActiveSubscriptionInfoList();
            poll = active == null || !active.isEmpty();
            for (int phoneId = 0; phoneId < mTelephony.getActiveModemCount(); phoneId++) {
                SlotState state = getState(phoneId);
                if (state.equals(mStates.get(phoneId))) {
                    continue;
                }
                Log.i(TAG, "phoneId=" + phoneId + " " + state);
                if (SubscriptionManager.isValidSubscriptionId(state.subscriptionId)) {
                    mCarrierConfig.notifyConfigChangedForSubId(state.subscriptionId);
                }
                mStates.put(phoneId, state);
            }
        } catch (RuntimeException exception) {
            poll = true;
            Log.e(TAG, "Unable to refresh IMS configuration", exception);
        }
        if (poll) {
            mHandler.postDelayed(mRefresh, REFRESH_INTERVAL_MILLIS);
        }
    }

    void dump(PrintWriter writer) {
        writer.println("Delegate package: " + CarrierConfigDelegate.PACKAGE_NAME);
        writer.println("VoNR default: " + mApplication.getResources().getBoolean(
                R.bool.config_vonr_enabled_by_default));
        for (int phoneId = 0; phoneId < mTelephony.getActiveModemCount(); phoneId++) {
            writer.println("phoneId=" + phoneId + " " + getState(phoneId));
        }
    }

    static final class SlotState {
        final int subscriptionId;
        final boolean loaded;
        final boolean enabled;
        final boolean allowed;

        SlotState(int subscriptionId, boolean loaded, boolean enabled, boolean allowed) {
            this.subscriptionId = subscriptionId;
            this.loaded = loaded;
            this.enabled = enabled;
            this.allowed = allowed;
        }

        @Override
        public boolean equals(Object other) {
            if (!(other instanceof SlotState)) {
                return false;
            }
            SlotState state = (SlotState) other;
            return subscriptionId == state.subscriptionId && loaded == state.loaded
                    && enabled == state.enabled && allowed == state.allowed;
        }

        @Override
        public int hashCode() {
            return Objects.hash(subscriptionId, loaded, enabled, allowed);
        }

        @Override
        public String toString() {
            return "subId=" + subscriptionId + " loaded=" + loaded
                    + " vendorEnabled=" + enabled + " modemAllowed=" + allowed;
        }
    }
}
