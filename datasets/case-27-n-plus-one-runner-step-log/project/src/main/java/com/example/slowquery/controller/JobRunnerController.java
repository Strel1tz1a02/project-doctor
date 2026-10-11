package com.example.slowquery.controller;

import com.example.slowquery.dto.RunDetailVO;
import com.example.slowquery.service.JobRunnerService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/runner")
public class JobRunnerController {

    private final JobRunnerService jobRunnerService;

    public JobRunnerController(JobRunnerService jobRunnerService) {
        this.jobRunnerService = jobRunnerService;
    }

    @GetMapping("/run-details")
    public RunDetailVO runDetails(
            @RequestParam(defaultValue = "run-001") String runId,
            @RequestParam(defaultValue = "200") int limit) {
        return jobRunnerService.runDetails(runId, limit);
    }
}
