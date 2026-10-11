package com.example.slowquery.controller;

import com.example.slowquery.service.LegacyBatchReportService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/orders")
public class LegacyBatchReportController {

    private final LegacyBatchReportService legacyBatchReportService;

    public LegacyBatchReportController(LegacyBatchReportService legacyBatchReportService) {
        this.legacyBatchReportService = legacyBatchReportService;
    }

    @GetMapping("/legacy-batch")
    public String legacyBatch(@RequestParam(defaultValue = "50") int size) {
        return legacyBatchReportService.loadBatch(size);
    }
}
