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
        Integer count = jdbcTemplate.queryForObject("SELECT COUNT(*) FROM jobs", Integer.class);
        if (count != null && count > 0) {
            return;
        }

        int runCount = 50;
        int jobsPerRun = 400;
        int stepsPerJob = 6;
        int logsPerJob = 12;
        Random random = new Random(42);
        long now = System.currentTimeMillis();

        List<Object[]> jobs = new ArrayList<>();
        for (int r = 1; r <= runCount; r++) {
            String runId = "run-" + String.format("%03d", r);
            for (int j = 1; j <= jobsPerRun; j++) {
                String jobName = "job-" + r + "-" + j;
                long createdAtMs = now - random.nextInt(24 * 3600) * 1000L;
                jobs.add(new Object[]{runId, jobName, createdAtMs});
                if (jobs.size() >= 5000) {
                    jdbcTemplate.batchUpdate(
                            "INSERT INTO jobs(run_id, job_name, created_at_ms) VALUES (?, ?, ?)",
                            jobs
                    );
                    jobs.clear();
                }
            }
        }
        if (!jobs.isEmpty()) {
            jdbcTemplate.batchUpdate(
                    "INSERT INTO jobs(run_id, job_name, created_at_ms) VALUES (?, ?, ?)",
                    jobs
            );
        }

        List<Long> jobIds = jdbcTemplate.queryForList("SELECT job_id FROM jobs ORDER BY job_id", Long.class);
        String[] levels = {"INFO", "WARN", "ERROR", "DEBUG"};

        List<Object[]> steps = new ArrayList<>();
        List<Object[]> logs = new ArrayList<>();
        for (Long jobId : jobIds) {
            for (int s = 1; s <= stepsPerJob; s++) {
                steps.add(new Object[]{jobId, "step-" + s, s});
                if (steps.size() >= 5000) {
                    jdbcTemplate.batchUpdate(
                            "INSERT INTO job_steps(job_id, step_name, step_order) VALUES (?, ?, ?)",
                            steps
                    );
                    steps.clear();
                }
            }
            for (int l = 1; l <= logsPerJob; l++) {
                String level = levels[random.nextInt(levels.length)];
                logs.add(new Object[]{jobId, level, "任务 " + jobId + " 日志行 " + l, now - l * 1000L});
                if (logs.size() >= 5000) {
                    jdbcTemplate.batchUpdate(
                            "INSERT INTO job_logs(job_id, level, message, created_at_ms) VALUES (?, ?, ?, ?)",
                            logs
                    );
                    logs.clear();
                }
            }
        }
        if (!steps.isEmpty()) {
            jdbcTemplate.batchUpdate(
                    "INSERT INTO job_steps(job_id, step_name, step_order) VALUES (?, ?, ?)",
                    steps
            );
        }
        if (!logs.isEmpty()) {
            jdbcTemplate.batchUpdate(
                    "INSERT INTO job_logs(job_id, level, message, created_at_ms) VALUES (?, ?, ?, ?)",
                    logs
            );
        }

        System.out.println("测试数据初始化完成：runs=" + runCount + ", jobs=" + (runCount * jobsPerRun)
                + ", job_steps=" + (runCount * jobsPerRun * stepsPerJob)
                + ", job_logs=" + (runCount * jobsPerRun * logsPerJob));
    }
}
