package com.example.gcammod;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.media.MediaPlayer;
import android.net.Uri;
import android.os.Bundle;
import android.view.View;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.VideoView;

import java.io.InputStream;

/**
 * Minimal standalone Activity added to GoogleCamera's own APK. Launched by
 * a new button injected into BottomBar. Immediately opens the system
 * document picker; once a file is picked, shows it full-screen. Tapping
 * the screen finishes the activity, returning to the live camera behind it.
 *
 * Deliberately plain Java + only platform (android.*) classes -- no Kotlin,
 * no external libraries -- so it has zero runtime dependencies beyond what
 * every Android app already has, and drops cleanly into GoogleCamera's
 * existing dex.
 */
public class OverlayActivity extends Activity {

    private static final int PICK_REQUEST_CODE = 1001;

    private ImageView imageView;
    private VideoView videoView;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.BLACK);
        root.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                finish();
            }
        });

        imageView = new ImageView(this);
        imageView.setScaleType(ImageView.ScaleType.FIT_CENTER);
        imageView.setVisibility(View.GONE);

        videoView = new VideoView(this);
        videoView.setVisibility(View.GONE);

        FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT);
        root.addView(imageView, lp);
        root.addView(videoView, lp);
        setContentView(root);

        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.setType("*/*");
        intent.putExtra(Intent.EXTRA_MIME_TYPES, new String[]{"image/*", "video/*"});
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        startActivityForResult(intent, PICK_REQUEST_CODE);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != PICK_REQUEST_CODE) {
            return;
        }
        Uri uri = (data != null) ? data.getData() : null;
        if (uri == null) {
            finish();
            return;
        }

        String mimeType = getContentResolver().getType(uri);
        if (mimeType != null && mimeType.startsWith("video")) {
            videoView.setVideoURI(uri);
            videoView.setOnPreparedListener(new MediaPlayer.OnPreparedListener() {
                @Override
                public void onPrepared(MediaPlayer mp) {
                    mp.start();
                }
            });
            videoView.setVisibility(View.VISIBLE);
        } else {
            try {
                InputStream input = getContentResolver().openInputStream(uri);
                if (input != null) {
                    Bitmap bitmap = BitmapFactory.decodeStream(input);
                    imageView.setImageBitmap(bitmap);
                    input.close();
                }
            } catch (Exception e) {
                // Worst case the image just doesn't show; not fatal.
            }
            imageView.setVisibility(View.VISIBLE);
        }
    }
}
