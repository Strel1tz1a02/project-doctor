package com.example.slowquery.controller;

import com.example.slowquery.service.LegacyReportService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/orders")
public class LegacyReportController {

    private final LegacyReportService legacyReportService;

    public LegacyReportController(LegacyReportService legacyReportService) {
        this.legacyReportService = legacyReportService;
    }

    @GetMapping("/legacy-recent")
    public String legacyRecent(@RequestParam(defaultValue = "50") int size) {
        return legacyReportService.loadRecent(size);
    }
}
