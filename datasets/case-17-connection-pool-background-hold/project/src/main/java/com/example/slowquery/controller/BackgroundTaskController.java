package com.example.slowquery.controller;

import com.example.slowquery.service.BackgroundTaskService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/reports")
public class BackgroundTaskController {

    private final BackgroundTaskService backgroundTaskService;

    public BackgroundTaskController(BackgroundTaskService backgroundTaskService) {
        this.backgroundTaskService = backgroundTaskService;
    }

    @GetMapping("/background")
    public String background(@RequestParam(defaultValue = "16") int tasks,
                             @RequestParam(defaultValue = "800") int pollIntervalMs) {
        return backgroundTaskService.runBatch(tasks, pollIntervalMs);
    }
}
