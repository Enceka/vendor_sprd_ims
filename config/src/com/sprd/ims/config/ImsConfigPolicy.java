package com.sprd.ims.config;

import android.os.PersistableBundle;
import android.telephony.CarrierConfigManager;

final class ImsConfigPolicy {
    static boolean isModemAllowed(String property, int phoneId) {
        if (property == null || phoneId < 0) {
            return false;
        }
        String[] values = property.split(",", -1);
        return phoneId < values.length && "1".equals(values[phoneId]);
    }

    static PersistableBundle apply(PersistableBundle original, boolean simLoaded,
            boolean vendorEnabled, boolean modemAllowed, boolean vonrDefault) {
        PersistableBundle config = new PersistableBundle(original);
        if (!simLoaded) {
            return config;
        }
        if (!vendorEnabled) {
            config.putBoolean(CarrierConfigManager.KEY_CARRIER_VOLTE_AVAILABLE_BOOL, false);
        } else if (modemAllowed) {
            config.putBoolean(CarrierConfigManager.KEY_CARRIER_VOLTE_AVAILABLE_BOOL, true);
        }
        if (!config.containsKey(CarrierConfigManager.KEY_VONR_ENABLED_BOOL)) {
            config.putBoolean(CarrierConfigManager.KEY_VONR_ENABLED_BOOL, vonrDefault);
        }
        return config;
    }

    private ImsConfigPolicy() {
    }
}
