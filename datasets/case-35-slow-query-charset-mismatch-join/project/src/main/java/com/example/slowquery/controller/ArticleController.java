package com.example.slowquery.controller;

import com.example.slowquery.dto.ArticleVO;
import com.example.slowquery.service.ArticleService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/articles")
public class ArticleController {

    private final ArticleService articleService;

    public ArticleController(ArticleService articleService) {
        this.articleService = articleService;
    }

    @GetMapping("/by-author")
    public List<ArticleVO> byAuthor(@RequestParam(defaultValue = "A000012") String authorCode) {
        return articleService.findByAuthorCode(authorCode);
    }
}
