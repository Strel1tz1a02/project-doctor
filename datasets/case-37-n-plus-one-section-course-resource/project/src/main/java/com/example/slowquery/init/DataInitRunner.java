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
        Integer sections = jdbcTemplate.queryForObject("SELECT COUNT(*) FROM sections", Integer.class);
        if (sections != null && sections > 0) {
            return;
        }

        int courseTotal = 5000;
        int sectionTotal = 200000;
        int resourceTotal = 400000;
        Random random = new Random(42);
        long now = System.currentTimeMillis();

        List<Object[]> courseRows = new ArrayList<>();
        for (int i = 1; i <= courseTotal; i++) {
            courseRows.add(new Object[]{"course-" + i, now - random.nextInt(365 * 24 * 3600) * 1000L});
            if (courseRows.size() >= 5000) {
                jdbcTemplate.batchUpdate("INSERT INTO courses(title, created_at_ms) VALUES (?, ?)", courseRows);
                courseRows.clear();
            }
        }
        if (!courseRows.isEmpty()) {
            jdbcTemplate.batchUpdate("INSERT INTO courses(title, created_at_ms) VALUES (?, ?)", courseRows);
        }

        List<Object[]> sectionRows = new ArrayList<>();
        for (int i = 1; i <= sectionTotal; i++) {
            long courseId = 1 + random.nextInt(courseTotal);
            long createdAtMs = now - random.nextInt(365 * 24 * 3600) * 1000L;
            sectionRows.add(new Object[]{courseId, "section-" + i, createdAtMs});
            if (sectionRows.size() >= 5000) {
                jdbcTemplate.batchUpdate("INSERT INTO sections(course_id, title, created_at_ms) VALUES (?, ?, ?)", sectionRows);
                sectionRows.clear();
            }
        }
        if (!sectionRows.isEmpty()) {
            jdbcTemplate.batchUpdate("INSERT INTO sections(course_id, title, created_at_ms) VALUES (?, ?, ?)", sectionRows);
        }

        List<Object[]> resourceRows = new ArrayList<>();
        for (int i = 1; i <= resourceTotal; i++) {
            long sectionId = 1 + random.nextInt(sectionTotal);
            long createdAtMs = now - random.nextInt(365 * 24 * 3600) * 1000L;
            resourceRows.add(new Object[]{sectionId, createdAtMs});
            if (resourceRows.size() >= 5000) {
                jdbcTemplate.batchUpdate("INSERT INTO resources(section_id, created_at_ms) VALUES (?, ?)", resourceRows);
                resourceRows.clear();
            }
        }
        if (!resourceRows.isEmpty()) {
            jdbcTemplate.batchUpdate("INSERT INTO resources(section_id, created_at_ms) VALUES (?, ?)", resourceRows);
        }

        System.out.println("测试数据初始化完成：courses=" + courseTotal + "，sections=" + sectionTotal + "，resources=" + resourceTotal);
    }
}
