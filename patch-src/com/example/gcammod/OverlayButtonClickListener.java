package com.example.gcammod;

import android.content.Context;
import android.content.Intent;
import android.view.View;

/**
 * Referenced by exact class name from the hand-written smali insertion in
 * BottomBar.onFinishInflate(). Kept as a real named class (rather than an
 * anonymous/lambda) precisely so it has a stable name for that smali edit
 * to reference.
 */
public class OverlayButtonClickListener implements View.OnClickListener {
    private final Context context;

    public OverlayButtonClickListener(Context context) {
        this.context = context;
    }

    @Override
    public void onClick(View v) {
        Intent intent = new Intent(context, OverlayActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        context.startActivity(intent);
    }
}
