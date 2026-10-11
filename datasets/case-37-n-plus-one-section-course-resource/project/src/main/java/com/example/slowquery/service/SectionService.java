package com.example.slowquery.service;

import com.example.slowquery.dto.SectionVO;
import com.example.slowquery.mapper.SectionMapper;
import com.example.slowquery.model.Section;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;

@Service
public class SectionService {

    private final SectionMapper sectionMapper;

    public SectionService(SectionMapper sectionMapper) {
        this.sectionMapper = sectionMapper;
    }

    public List<SectionVO> buildSections(int size) {
        List<Section> sections = sectionMapper.findRecentSections(size);
        List<SectionVO> result = new ArrayList<>();
        for (Section section : sections) {
            SectionVO vo = new SectionVO();
            vo.setSectionId(section.getId());
            vo.setTitle(section.getTitle());
            vo.setCourseTitle(sectionMapper.findCourseTitleById(section.getCourseId()));
            result.add(vo);
        }
        for (SectionVO vo : result) {
            vo.setResourceCount(sectionMapper.countResourcesBySectionId(vo.getSectionId()));
        }
        return result;
    }
}
