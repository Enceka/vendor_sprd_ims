package com.sprd.ims.config;

import android.app.Application;

public final class SprdImsApplication extends Application {
    private ImsConfigController mController;

    @Override
    public void onCreate() {
        super.onCreate();
        mController = new ImsConfigController(this);
        mController.start();
    }

    ImsConfigController getController() {
        return mController;
    }
}
