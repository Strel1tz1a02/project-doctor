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
        Integer repositories = jdbcTemplate.queryForObject("SELECT COUNT(*) FROM repositories", Integer.class);
        if (repositories != null && repositories > 0) {
            return;
        }

        int committerTotal = 50000;
        int repositoryTotal = 20000;
        int commitTotal = 200000;
        Random random = new Random(42);
        long now = System.currentTimeMillis();

        List<Object[]> committerRows = new ArrayList<>();
        for (int i = 1; i <= committerTotal; i++) {
            committerRows.add(new Object[]{"committer-" + i});
            if (committerRows.size() >= 5000) {
                jdbcTemplate.batchUpdate("INSERT INTO committers(name) VALUES (?)", committerRows);
                committerRows.clear();
            }
        }
        if (!committerRows.isEmpty()) {
            jdbcTemplate.batchUpdate("INSERT INTO committers(name) VALUES (?)", committerRows);
        }

        List<Object[]> repositoryRows = new ArrayList<>();
        for (int i = 1; i <= repositoryTotal; i++) {
            long createdAtMs = now - random.nextInt(365 * 24 * 3600) * 1000L;
            repositoryRows.add(new Object[]{"org-" + (i % 1000), "repo-" + i, createdAtMs});
            if (repositoryRows.size() >= 5000) {
                jdbcTemplate.batchUpdate("INSERT INTO repositories(owner, name, created_at_ms) VALUES (?, ?, ?)", repositoryRows);
                repositoryRows.clear();
            }
        }
        if (!repositoryRows.isEmpty()) {
            jdbcTemplate.batchUpdate("INSERT INTO repositories(owner, name, created_at_ms) VALUES (?, ?, ?)", repositoryRows);
        }

        List<Object[]> commitRows = new ArrayList<>();
        for (int i = 1; i <= commitTotal; i++) {
            long repositoryId = 1 + random.nextInt(repositoryTotal);
            long committerId = 1 + random.nextInt(committerTotal);
            commitRows.add(new Object[]{repositoryId, committerId, "commit-" + i});
            if (commitRows.size() >= 5000) {
                jdbcTemplate.batchUpdate("INSERT INTO commits(repository_id, committer_id, message) VALUES (?, ?, ?)", commitRows);
                commitRows.clear();
            }
        }
        if (!commitRows.isEmpty()) {
            jdbcTemplate.batchUpdate("INSERT INTO commits(repository_id, committer_id, message) VALUES (?, ?, ?)", commitRows);
        }

        System.out.println("测试数据初始化完成：committers=" + committerTotal + "，repositories=" + repositoryTotal + "，commits=" + commitTotal);
    }
}
