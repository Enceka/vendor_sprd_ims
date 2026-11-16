package com.sprd.ims.config;

import android.Manifest;
import android.app.Service;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Binder;
import android.os.Bundle;
import android.os.IBinder;
import android.os.PersistableBundle;
import android.os.ResultReceiver;
import android.service.carrier.CarrierIdentifier;
import android.service.carrier.CarrierService;
import android.service.carrier.CarrierService.ICarrierServiceWrapper;
import android.service.carrier.ICarrierService;
import android.telephony.SubscriptionManager;
import android.util.Log;

import java.io.FileDescriptor;
import java.io.PrintWriter;

public final class SprdCarrierConfigService extends Service {
    private static final String TAG = "SprdImsConfig";

    private final ICarrierService.Stub mBinder = new ICarrierService.Stub() {
        @Override
        public void getCarrierConfig(int phoneId, CarrierIdentifier identifier,
                ResultReceiver result) {
            enforceCallingOrSelfPermission(Manifest.permission.BIND_CARRIER_SERVICES, TAG);
            if (result == null) {
                return;
            }
            try {
                Bundle data = new Bundle();
                data.putParcelable(ICarrierServiceWrapper.KEY_CONFIG_BUNDLE,
                        loadConfig(phoneId, identifier));
                result.send(ICarrierServiceWrapper.RESULT_OK, data);
            } catch (RuntimeException exception) {
                Log.e(TAG, "Cannot load configuration for phoneId=" + phoneId, exception);
                result.send(ICarrierServiceWrapper.RESULT_ERROR, null);
            }
        }

        @Override
        protected void dump(FileDescriptor descriptor, PrintWriter writer, String[] args) {
            if (checkCallingOrSelfPermission(Manifest.permission.DUMP)
                    != PackageManager.PERMISSION_GRANTED) {
                writer.println("Permission denied: DUMP is required");
                return;
            }
            SprdCarrierConfigService.this.dump(descriptor, writer, args);
        }
    };

    private ImsConfigController getController() {
        return ((SprdImsApplication) getApplication()).getController();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return CarrierService.CARRIER_SERVICE_INTERFACE.equals(intent.getAction()) ? mBinder : null;
    }

    private PersistableBundle loadConfig(int phoneId, CarrierIdentifier identifier) {
        long token = Binder.clearCallingIdentity();
        try {
            if (!SubscriptionManager.isValidPhoneId(phoneId)) {
                throw new IllegalArgumentException("Invalid logical phoneId=" + phoneId);
            }
            ImsConfigController controller = getController();
            ImsConfigController.SlotState before = controller.getState(phoneId);
            PersistableBundle original = controller.getDelegate().load(phoneId, identifier);
            if (identifier == null) {
                Log.i(TAG, "Returning the original no-SIM configuration for phoneId=" + phoneId);
                return original;
            }
            ImsConfigController.SlotState state = controller.getState(phoneId);
            boolean loaded = before.loaded && state.loaded
                    && before.subscriptionId == state.subscriptionId
                    && controller.matchesCarrier(state.subscriptionId, identifier);
            PersistableBundle config = ImsConfigPolicy.apply(original, loaded, state.enabled,
                    state.allowed, getResources().getBoolean(R.bool.config_vonr_enabled_by_default));
            Log.i(TAG, "Loaded configuration for phoneId=" + phoneId + " " + state
                    + " requestMatched=" + loaded);
            return config;
        } finally {
            Binder.restoreCallingIdentity(token);
        }
    }

    @Override
    protected void dump(FileDescriptor descriptor, PrintWriter writer, String[] args) {
        long token = Binder.clearCallingIdentity();
        try {
            getController().dump(writer);
        } finally {
            Binder.restoreCallingIdentity(token);
        }
    }
}
