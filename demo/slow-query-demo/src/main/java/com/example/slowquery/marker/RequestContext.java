package com.example.slowquery.marker;

import java.util.regex.Pattern;

/**
 * 线程内请求关联上下文：由 {@link RequestIdFilter} 写入、请求结束时清理。
 *
 * <p>Project Doctor 平台每次请求都会带上 {@code X-Project-Doctor-Request-Id}，
 * 只有 32 位十六进制格式才会被接受，避免脏数据进入 SQL 标记。
 */
public final class RequestContext {

    private static final ThreadLocal<String> REQUEST_ID = new ThreadLocal<>();
    private static final Pattern HEX32 = Pattern.compile("[a-f0-9]{32}");

    private RequestContext() {
    }

    public static void setRequestId(String id) {
        if (id != null && HEX32.matcher(id).matches()) {
            REQUEST_ID.set(id);
        }
    }

    public static String getRequestId() {
        return REQUEST_ID.get();
    }

    public static void clear() {
        REQUEST_ID.remove();
    }
}
