package com.example.slowquery.controller;

import com.example.slowquery.dto.SectionVO;
import com.example.slowquery.service.SectionService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/sections")
public class SectionController {

    private final SectionService sectionService;

    public SectionController(SectionService sectionService) {
        this.sectionService = sectionService;
    }

    @GetMapping("/recent")
    public List<SectionVO> recent(@RequestParam(defaultValue = "100") int size) {
        return sectionService.buildSections(size);
    }
}
