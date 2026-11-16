package com.sprd.ims.config;

import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.ServiceConnection;
import android.os.Bundle;
import android.os.Handler;
import android.os.IBinder;
import android.os.PersistableBundle;
import android.os.RemoteException;
import android.os.ResultReceiver;
import android.service.carrier.CarrierIdentifier;
import android.service.carrier.CarrierService;
import android.service.carrier.ICarrierService;
import android.util.Log;

import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

final class CarrierConfigDelegate {
    static final String PACKAGE_NAME = "com.android.carrierconfig";
    private static final String TAG = "SprdImsConfig";
    private static final long TIMEOUT_SECONDS = 5;

    private final Context mContext;
    private final Handler mHandler;
    private final Runnable mOnConnected;
    private CompletableFuture<ICarrierService> mConnection = new CompletableFuture<>();
    private boolean mBound;

    private final ServiceConnection mServiceConnection = new ServiceConnection() {
        @Override
        public void onServiceConnected(ComponentName name, IBinder binder) {
            synchronized (CarrierConfigDelegate.this) {
                mConnection.complete(ICarrierService.Stub.asInterface(binder));
            }
            Log.i(TAG, "Connected to the original CarrierConfig service");
            mOnConnected.run();
        }

        @Override
        public void onServiceDisconnected(ComponentName name) {
            synchronized (CarrierConfigDelegate.this) {
                mConnection = new CompletableFuture<>();
            }
        }

        @Override
        public void onBindingDied(ComponentName name) {
            rebind();
        }

        @Override
        public void onNullBinding(ComponentName name) {
            rebind();
        }
    };

    CarrierConfigDelegate(Context context, Handler handler, Runnable onConnected) {
        mContext = context;
        mHandler = handler;
        mOnConnected = onConnected;
    }

    void bind() {
        if (mBound) {
            return;
        }
        Intent intent = new Intent(CarrierService.CARRIER_SERVICE_INTERFACE);
        intent.setPackage(PACKAGE_NAME);
        try {
            mBound = mContext.bindService(intent, mServiceConnection, Context.BIND_AUTO_CREATE);
        } catch (SecurityException exception) {
            Log.e(TAG, "Cannot bind the original CarrierConfig service", exception);
        }
        if (!mBound) {
            mHandler.postDelayed(this::bind, TimeUnit.SECONDS.toMillis(TIMEOUT_SECONDS));
        }
    }

    void rebind() {
        if (mBound) {
            mContext.unbindService(mServiceConnection);
            mBound = false;
        }
        synchronized (this) {
            mConnection = new CompletableFuture<>();
        }
        mHandler.postDelayed(this::bind, TimeUnit.SECONDS.toMillis(1));
    }

    PersistableBundle load(int phoneId, CarrierIdentifier identifier) {
        CompletableFuture<ICarrierService> connection;
        synchronized (this) {
            connection = mConnection;
        }
        CompletableFuture<PersistableBundle> result = new CompletableFuture<>();
        try {
            ICarrierService service = connection.get(TIMEOUT_SECONDS, TimeUnit.SECONDS);
            service.getCarrierConfig(phoneId, identifier, new ResultReceiver(null) {
                @Override
                protected void onReceiveResult(int resultCode, Bundle data) {
                    PersistableBundle config = data == null ? null : data.getParcelable(
                            CarrierService.ICarrierServiceWrapper.KEY_CONFIG_BUNDLE,
                            PersistableBundle.class);
                    if (resultCode == CarrierService.ICarrierServiceWrapper.RESULT_OK
                            && config != null) {
                        result.complete(config);
                    } else {
                        result.completeExceptionally(new IllegalStateException(
                                "Original CarrierConfig service did not return a configuration"));
                    }
                }
            });
            return result.get(TIMEOUT_SECONDS, TimeUnit.SECONDS);
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("CarrierConfig delegation interrupted", exception);
        } catch (ExecutionException | TimeoutException | RemoteException exception) {
            throw new IllegalStateException("CarrierConfig delegation failed", exception);
        }
    }
}
