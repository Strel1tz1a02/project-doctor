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
        Integer count = jdbcTemplate.queryForObject("SELECT COUNT(*) FROM members", Integer.class);
        if (count != null && count > 0) {
            return;
        }

        int memberTotal = 300000;
        Random random = new Random(42);
        long now = System.currentTimeMillis();
        String[] nicknames = {"alice", "bob", "carol", "dave", "erin", "frank", "grace", "heidi"};

        List<Object[]> rows = new ArrayList<>();
        for (int i = 1; i <= memberTotal; i++) {
            String memberNo = String.valueOf(100000000L + i);
            String nickname = nicknames[random.nextInt(nicknames.length)];
            int roll = random.nextInt(100);
            String level = roll < 40 ? "BRONZE"
                    : (roll < 70 ? "SILVER"
                    : (roll < 90 ? "GOLD" : "PLATINUM"));
            long createdAtMs = now - random.nextInt(730 * 24 * 3600) * 1000L;
            rows.add(new Object[]{memberNo, nickname, level, createdAtMs});

            if (rows.size() >= 5000) {
                jdbcTemplate.batchUpdate(
                        "INSERT INTO members(member_no, nickname, level, created_at_ms) VALUES (?, ?, ?, ?)",
                        rows
                );
                rows.clear();
            }
        }

        if (!rows.isEmpty()) {
            jdbcTemplate.batchUpdate(
                    "INSERT INTO members(member_no, nickname, level, created_at_ms) VALUES (?, ?, ?, ?)",
                    rows
            );
        }

        System.out.println("测试数据初始化完成：members=" + memberTotal);
    }
}
