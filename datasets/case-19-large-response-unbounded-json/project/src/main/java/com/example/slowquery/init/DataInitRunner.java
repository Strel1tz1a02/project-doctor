package com.example.slowquery.init;

import org.springframework.boot.CommandLineRunner;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.sql.Timestamp;
import java.util.ArrayList;
import java.util.List;
import java.util.Random;

@Component
public class DataInitRunner implements CommandLineRunner {

    private static final String PAYLOAD_SEGMENT =
            "{\"asset\":\"release-asset\",\"size\":1048576,\"url\":\"https://example.invalid/release/download\"},";

    private final JdbcTemplate jdbcTemplate;

    public DataInitRunner(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    @Override
    public void run(String... args) {
        Integer releaseCount = jdbcTemplate.queryForObject("SELECT COUNT(*) FROM provider_releases", Integer.class);
        if (releaseCount != null && releaseCount > 0) {
            return;
        }

        int releaseTotal = 5000;
        Random random = new Random(42);
        String[] providers = {"signal", "github", "npm", "pypi", "maven"};
        long now = System.currentTimeMillis();

        List<Object[]> releases = new ArrayList<>();
        for (int i = 1; i <= releaseTotal; i++) {
            String provider = providers[i % providers.length];
            String releaseTag = "v" + (i / 100) + "." + (i % 100) + ".0";
            String payload = buildPayload(i);
            Timestamp createdAt = new Timestamp(now - random.nextInt(365 * 24 * 3600) * 1000L);

            releases.add(new Object[]{provider, releaseTag, payload, createdAt});

            if (releases.size() >= 500) {
                jdbcTemplate.batchUpdate(
                        "INSERT INTO provider_releases(provider, release_tag, payload, created_at) VALUES (?, ?, ?, ?)",
                        releases
                );
                releases.clear();
            }
        }

        if (!releases.isEmpty()) {
            jdbcTemplate.batchUpdate(
                    "INSERT INTO provider_releases(provider, release_tag, payload, created_at) VALUES (?, ?, ?, ?)",
                    releases
            );
        }

        System.out.println("测试数据初始化完成：provider_releases=" + releaseTotal);
    }

    private static String buildPayload(int index) {
        StringBuilder payload = new StringBuilder();
        payload.append("{\"release\":").append(index).append(",\"assets\":[");
        while (payload.length() < 6000) {
            payload.append(PAYLOAD_SEGMENT);
        }
        payload.append("]}");
        return payload.toString();
    }
}
