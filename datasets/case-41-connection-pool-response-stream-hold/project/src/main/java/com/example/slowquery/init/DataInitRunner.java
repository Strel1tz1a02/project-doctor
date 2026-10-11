package com.example.slowquery.init;

import org.springframework.boot.CommandLineRunner;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;
import java.util.Random;

@Component
public class DataInitRunner implements CommandLineRunner {

    private static final String[] SEGMENTS = {"retail", "wholesale", "online", "partner", "internal"};

    private final JdbcTemplate jdbcTemplate;

    public DataInitRunner(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    @Override
    public void run(String... args) {
        Integer count = jdbcTemplate.queryForObject("SELECT COUNT(*) FROM export_rows", Integer.class);
        if (count != null && count > 0) {
            return;
        }

        int rowTotal = 200000;
        Random random = new Random(42);
        long now = System.currentTimeMillis();

        List<Object[]> rows = new ArrayList<>();
        for (int i = 1; i <= rowTotal; i++) {
            String segment = SEGMENTS[random.nextInt(SEGMENTS.length)];
            long amount = random.nextInt(1000000);
            long createdAtMs = now - random.nextInt(90 * 24 * 3600) * 1000L;
            rows.add(new Object[]{segment, amount, createdAtMs});
            if (rows.size() >= 5000) {
                jdbcTemplate.batchUpdate(
                        "INSERT INTO export_rows(segment, amount, created_at_ms) VALUES (?, ?, ?)",
                        rows
                );
                rows.clear();
            }
        }
        if (!rows.isEmpty()) {
            jdbcTemplate.batchUpdate(
                    "INSERT INTO export_rows(segment, amount, created_at_ms) VALUES (?, ?, ?)",
                    rows
            );
        }

        System.out.println("测试数据初始化完成：export_rows=" + rowTotal + "（segment 取自 5 个分区）");
    }
}
