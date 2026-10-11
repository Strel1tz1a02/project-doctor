package com.example.slowquery.config;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * 摘要接口的行数上限解析器。
 *
 * <p>约定：摘要接口返回的行数必须落在 {@code [1, HARD_MAX]} 区间内。
 * <p>显式配置（{@code report.summary.limit}）存在且合法时，解析后夹取到该区间；
 * 配置缺失或不合法时回退到 {@link #FALLBACK_DEFAULT}。
 */
@Component
public class SummaryLimitResolver {

    /** 摘要接口允许返回的最大行数（硬上限）。 */
    public static final int HARD_MAX = 100;

    /** 配置缺失时的默认行数。 */
    private static final int FALLBACK_DEFAULT = 5000;

    private final String configuredLimit;

    public SummaryLimitResolver(@Value("${report.summary.limit:}") String configuredLimit) {
        this.configuredLimit = configuredLimit;
    }

    /**
     * 解析生效的摘要行数上限。
     */
    public int resolve() {
        if (configuredLimit == null || configuredLimit.isBlank()) {
            return fallback();
        }
        int parsed;
        try {
            parsed = Integer.parseInt(configuredLimit.trim());
        } catch (NumberFormatException ex) {
            return fallback();
        }
        return clamp(parsed);
    }

    /**
     * 回退路径：配置缺失或非法时取默认值。
     */
    private static int fallback() {
        return FALLBACK_DEFAULT;
    }

    private static int clamp(int value) {
        if (value < 1) {
            return 1;
        }
        return Math.min(value, HARD_MAX);
    }
}
