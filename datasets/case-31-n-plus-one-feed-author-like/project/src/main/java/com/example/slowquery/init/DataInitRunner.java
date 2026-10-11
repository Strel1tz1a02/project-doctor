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
        Integer posts = jdbcTemplate.queryForObject("SELECT COUNT(*) FROM posts", Integer.class);
        if (posts != null && posts > 0) {
            return;
        }

        int userTotal = 50000;
        int postTotal = 200000;
        int likeTotal = 400000;
        Random random = new Random(42);
        long now = System.currentTimeMillis();

        List<Object[]> users = new ArrayList<>();
        for (int i = 1; i <= userTotal; i++) {
            users.add(new Object[]{"user-" + i, now - random.nextInt(365 * 24 * 3600) * 1000L});
            if (users.size() >= 5000) {
                jdbcTemplate.batchUpdate("INSERT INTO users(nickname, created_at_ms) VALUES (?, ?)", users);
                users.clear();
            }
        }
        if (!users.isEmpty()) {
            jdbcTemplate.batchUpdate("INSERT INTO users(nickname, created_at_ms) VALUES (?, ?)", users);
        }

        List<Object[]> postRows = new ArrayList<>();
        for (int i = 1; i <= postTotal; i++) {
            long authorId = 1 + random.nextInt(userTotal);
            long createdAtMs = now - random.nextInt(365 * 24 * 3600) * 1000L;
            postRows.add(new Object[]{authorId, "post-" + i, createdAtMs});
            if (postRows.size() >= 5000) {
                jdbcTemplate.batchUpdate("INSERT INTO posts(author_id, content, created_at_ms) VALUES (?, ?, ?)", postRows);
                postRows.clear();
            }
        }
        if (!postRows.isEmpty()) {
            jdbcTemplate.batchUpdate("INSERT INTO posts(author_id, content, created_at_ms) VALUES (?, ?, ?)", postRows);
        }

        List<Object[]> likeRows = new ArrayList<>();
        for (int i = 1; i <= likeTotal; i++) {
            long postId = 1 + random.nextInt(postTotal);
            long createdAtMs = now - random.nextInt(365 * 24 * 3600) * 1000L;
            likeRows.add(new Object[]{postId, createdAtMs});
            if (likeRows.size() >= 5000) {
                jdbcTemplate.batchUpdate("INSERT INTO likes(post_id, created_at_ms) VALUES (?, ?)", likeRows);
                likeRows.clear();
            }
        }
        if (!likeRows.isEmpty()) {
            jdbcTemplate.batchUpdate("INSERT INTO likes(post_id, created_at_ms) VALUES (?, ?)", likeRows);
        }

        System.out.println("测试数据初始化完成：users=" + userTotal + "，posts=" + postTotal + "，likes=" + likeTotal);
    }
}
