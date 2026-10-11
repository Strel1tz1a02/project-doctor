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
        Integer count = jdbcTemplate.queryForObject("SELECT COUNT(*) FROM audit_events", Integer.class);
        if (count != null && count > 0) {
            return;
        }

        int eventTotal = 300000;
        Random random = new Random(42);
        long base = 1750000000000L;
        String[] actors = {"alice", "bob", "carol", "dave", "erin", "frank", "grace", "heidi"};
        String[] actions = {"LOGIN", "LOGOUT", "CREATE", "UPDATE", "DELETE", "EXPORT", "VIEW"};

        List<Object[]> rows = new ArrayList<>();
        for (int i = 1; i <= eventTotal; i++) {
            String actor = actors[random.nextInt(actors.length)];
            String action = actions[random.nextInt(actions.length)];
            long occurredAtMs = base - random.nextInt(180 * 24 * 3600) * 1000L;
            rows.add(new Object[]{actor, action, occurredAtMs});

            if (rows.size() >= 5000) {
                jdbcTemplate.batchUpdate(
                        "INSERT INTO audit_events(actor, action, occurred_at_ms) VALUES (?, ?, ?)",
                        rows
                );
                rows.clear();
            }
        }

        if (!rows.isEmpty()) {
            jdbcTemplate.batchUpdate(
                    "INSERT INTO audit_events(actor, action, occurred_at_ms) VALUES (?, ?, ?)",
                    rows
            );
        }

        System.out.println("测试数据初始化完成：audit_events=" + eventTotal);
    }
}
