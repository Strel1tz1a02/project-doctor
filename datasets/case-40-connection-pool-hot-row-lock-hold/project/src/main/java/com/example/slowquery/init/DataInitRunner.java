package com.example.slowquery.init;

import org.springframework.boot.CommandLineRunner;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;
import java.util.Random;

@Component
public class DataInitRunner implements CommandLineRunner {

    private final JdbcTemplate jdbcTemplate;

    public DataInitRunner(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    @Override
    public void run(String... args) {
        Integer count = jdbcTemplate.queryForObject("SELECT COUNT(*) FROM counters", Integer.class);
        if (count != null && count > 0) {
            return;
        }

        int counterTotal = 200000;
        Random random = new Random(42);
        long now = System.currentTimeMillis();

        List<Object[]> rows = new ArrayList<>();
        for (int i = 1; i <= counterTotal; i++) {
            String counterKey = "CNT-" + i;
            long value = random.nextInt(100000);
            long updatedAtMs = now - random.nextInt(30 * 24 * 3600) * 1000L;
            rows.add(new Object[]{counterKey, value, updatedAtMs});
            if (rows.size() >= 5000) {
                jdbcTemplate.batchUpdate(
                        "INSERT INTO counters(counter_key, value, updated_at_ms) VALUES (?, ?, ?)",
                        rows
                );
                rows.clear();
            }
        }
        if (!rows.isEmpty()) {
            jdbcTemplate.batchUpdate(
                    "INSERT INTO counters(counter_key, value, updated_at_ms) VALUES (?, ?, ?)",
                    rows
            );
        }

        System.out.println("测试数据初始化完成：counters=" + counterTotal + "（热点键 CNT-1）");
    }
}
