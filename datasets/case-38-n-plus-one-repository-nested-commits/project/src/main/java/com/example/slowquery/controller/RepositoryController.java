package com.example.slowquery.controller;

import com.example.slowquery.dto.RepositoryVO;
import com.example.slowquery.service.RepositoryService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/repositories")
public class RepositoryController {

    private final RepositoryService repositoryService;

    public RepositoryController(RepositoryService repositoryService) {
        this.repositoryService = repositoryService;
    }

    @GetMapping("/recent")
    public List<RepositoryVO> recent(@RequestParam(defaultValue = "20") int size) {
        return repositoryService.buildRepositories(size);
    }
}
