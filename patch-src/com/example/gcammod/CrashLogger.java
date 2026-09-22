package com.example.gcammod;

import android.content.Context;
import android.os.Environment;

import java.io.File;
import java.io.FileWriter;
import java.io.PrintWriter;
import java.text.SimpleDateFormat;
import java.util.Date;

/**
 * Writes crash stack traces and lifecycle breadcrumbs to a plain text file
 * under this app's external files directory (no special permission needed
 * on modern Android), so we can pull it via adb after the app fails --
 * useful when the failure happens too early/quietly for a live logcat
 * capture to reliably catch.
 *
 * Files land at:
 *   /sdcard/Android/data/com.example.gcammod/files/gcammod_debug.log
 *   /sdcard/Android/data/com.example.gcammod/files/gcammod_crash.log
 */
public class CrashLogger {

    public static void install(final Context context) {
        final Thread.UncaughtExceptionHandler previous = Thread.getDefaultUncaughtExceptionHandler();
        Thread.setDefaultUncaughtExceptionHandler(new Thread.UncaughtExceptionHandler() {
            @Override
            public void uncaughtException(Thread t, Throwable e) {
                try {
                    File dir = context.getExternalFilesDir(null);
                    File f = new File(dir, "gcammod_crash.log");
                    FileWriter fw = new FileWriter(f, true);
                    PrintWriter pw = new PrintWriter(fw);
                    pw.println("=== " + timestamp() + " uncaught on thread " + t.getName() + " ===");
                    e.printStackTrace(pw);
                    pw.println();
                    pw.flush();
                    pw.close();
                } catch (Throwable ignored) {
                    // If we can't log the crash, there's nothing more we can do here.
                }
                if (previous != null) {
                    previous.uncaughtException(t, e);
                }
            }
        });
        log(context, "CrashLogger installed");
    }

    public static void log(Context context, String message) {
        try {
            File dir = context.getExternalFilesDir(null);
            if (dir != null && !dir.exists()) {
                dir.mkdirs();
            }
            File f = new File(dir, "gcammod_debug.log");
            FileWriter fw = new FileWriter(f, true);
            PrintWriter pw = new PrintWriter(fw);
            pw.println(timestamp() + " " + message);
            pw.flush();
            pw.close();
        } catch (Throwable ignored) {
            // Logging must never itself cause a crash.
        }
    }

    private static String timestamp() {
        return new SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS").format(new Date());
    }
}
