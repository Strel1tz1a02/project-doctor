package com.example.slowquery.service;

import com.example.slowquery.dto.CommitVO;
import com.example.slowquery.dto.RepositoryVO;
import com.example.slowquery.mapper.RepositoryMapper;
import com.example.slowquery.model.Commit;
import com.example.slowquery.model.Repository;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;

@Service
public class RepositoryService {

    private final RepositoryMapper repositoryMapper;

    public RepositoryService(RepositoryMapper repositoryMapper) {
        this.repositoryMapper = repositoryMapper;
    }

    public List<RepositoryVO> buildRepositories(int size) {
        List<Repository> repositories = repositoryMapper.findRecentRepositories(size);
        List<RepositoryVO> result = new ArrayList<>();
        for (Repository repository : repositories) {
            RepositoryVO vo = new RepositoryVO();
            vo.setRepositoryId(repository.getId());
            vo.setName(repository.getOwner() + "/" + repository.getName());
            List<Commit> commits = repositoryMapper.findCommitsByRepositoryId(repository.getId());
            List<CommitVO> commitVOs = new ArrayList<>();
            for (Commit commit : commits) {
                CommitVO cvo = new CommitVO();
                cvo.setCommitId(commit.getId());
                cvo.setMessage(commit.getMessage());
                cvo.setCommitterName(repositoryMapper.findCommitterNameById(commit.getCommitterId()));
                commitVOs.add(cvo);
            }
            vo.setCommits(commitVOs);
            result.add(vo);
        }
        return result;
    }
}
